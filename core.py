"""core.py - 목재 휨·안전성 시뮬레이터 계산 로직 (화면 코드와 분리)

단위: 길이 mm, 힘 N, 응력·탄성계수 MPa (= N/mm²)

구성
 1) 상수·물성표 (임시값: 출처 확보 후 SPECIES 표만 교체)
 2) hankinson()            : 행킨슨 식으로 각도별 유효값 계산
 3) validate_inputs()      : 입력값 검증 (음수·문자·빈칸)
 4) analyze()              : 응력·처짐·판정·허용하중·하중-처짐 곡선
 5) estimate_grain_angle() : 나뭇결 사진에서 결 각도 추정
"""
import math

import numpy as np

# ---------------------------------------------------------------
# 1) 상수·물성표
# ---------------------------------------------------------------
# [임시값] 일반적인 범위를 가정한 값이며 공식 자료가 아님.
# E0, F0 : 결 방향(0°) 탄성계수·휨강도 / E90, F90 : 결 직각(90°) 값 (MPa)
SPECIES = {
    "소나무": {"E0": 9000, "E90": 450, "F0": 60, "F90": 4.0},
    "낙엽송": {"E0": 11000, "E90": 550, "F0": 70, "F90": 5.0},
    "삼나무": {"E0": 7500, "E90": 375, "F0": 50, "F90": 3.5},
    "10S등급(일반)": {"E0": 10000, "E90": 500, "F0": 40, "F90": 3.0},
    "12S등급(고강도)": {"E0": 12000, "E90": 600, "F0": 50, "F90": 4.0},
}

N_E = 2.0  # 행킨슨 지수 (탄성계수). 자료로 확인 후 조정
N_F = 2.0  # 행킨슨 지수 (강도). 자료로 확인 후 조정

# 적용 위치 -> 보 종류
POSITIONS = {
    "인테리어 파티션/수직루버 (양단 고정보)": "fixed",
    "벽면 아트월/가벽 (외팔보)": "cantilever",
    "가구상판/수평발판 (단순보)": "simple",
}

# 집중하중 P 기준 계수
#  M_max = c_M * P * L,  δ_max = c_d * P * L^3 / (E * I)
#  허용처짐 = span_factor * L / k  (외팔보는 경간 대신 2L 기준)
BEAMS = {
    "simple": {"name": "단순보", "c_M": 1 / 4, "c_d": 1 / 48, "span_factor": 1.0},
    "fixed": {"name": "양단 고정보", "c_M": 1 / 8, "c_d": 1 / 192, "span_factor": 1.0},
    "cantilever": {"name": "외팔보", "c_M": 1.0, "c_d": 1 / 3, "span_factor": 2.0},
}

# 판정 기준 (기본값, 화면에서 변경 가능)
DEFAULT_K = 240          # 허용처짐 = L/k
DEFAULT_EL_RATIO = 0.6   # 탄성 한계 = 휨강도 x 0.6 (임시)
DEFAULT_SF = 1.5         # 요구 안전율
WARN_RATIO = 0.8         # 한계의 80%를 넘으면 '주의'
POST_SLOPE = 0.2         # 탄성 한계 이후 강성 비율 (이중선형 가정)

LEVELS = ["안전", "주의", "경고"]


# ---------------------------------------------------------------
# 2) 행킨슨 식
# ---------------------------------------------------------------
def hankinson(p0, p90, theta_deg, n=2.0):
    """P(θ) = P0·P90 / (P0·sin^n θ + P90·cos^n θ)"""
    t = math.radians(theta_deg)
    return p0 * p90 / (p0 * abs(math.sin(t)) ** n + p90 * abs(math.cos(t)) ** n)


# ---------------------------------------------------------------
# 3) 입력 검증
# ---------------------------------------------------------------
def _to_number(text):
    """문자열을 숫자로 변환. 실패하면 (None, 이유)."""
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        s = str(text).strip().replace(",", "")
        if s == "":
            return None, "비어 있습니다"
        try:
            value = float(s)
        except ValueError:
            return None, "숫자가 아닙니다"
    if math.isnan(value) or math.isinf(value):
        return None, "유한한 숫자가 아닙니다"
    return value, None


def validate_inputs(raw):
    """raw: {'h','b','L','P','theta'} 값(문자열 가능).
    반환: (values, errors, warnings). errors가 있으면 계산하지 않는다."""
    labels = {"h": "부재 두께(h)", "b": "부재 폭(b)", "L": "부재 경간(L)", "P": "작용 하중(P)"}
    values, errors, warnings = {}, [], []

    for key, label in labels.items():
        value, why = _to_number(raw.get(key, ""))
        if why:
            errors.append(f"{label}: {why}")
        elif value <= 0:
            errors.append(f"{label}: 0보다 큰 값을 입력하세요 (입력값 {value:g})")
        else:
            values[key] = value

    theta, why = _to_number(raw.get("theta", 0))
    if why:
        errors.append(f"나뭇결 각도: {why}")
    elif not 0 <= theta <= 90:
        errors.append(f"나뭇결 각도: 0~90° 범위로 입력하세요 (입력값 {theta:g})")
    else:
        values["theta"] = theta

    if not errors:
        if values["L"] / values["h"] < 10:
            warnings.append("경간/두께 < 10 : 깊은 보라 전단변형이 커서 처짐이 실제보다 작게 계산될 수 있습니다.")
        if values["h"] / values["b"] > 3:
            warnings.append("두께/폭 > 3 : 옆으로 쓰러지는(측면 비틀림 좌굴) 위험이 있어 별도 검토가 필요합니다.")
    return values, errors, warnings


# ---------------------------------------------------------------
# 4) 해석·판정
# ---------------------------------------------------------------
def _grade(ratio, warn=WARN_RATIO):
    """한계 대비 비율(ratio)로 안전/주의/경고 판정 (작을수록 안전)."""
    if ratio <= warn:
        return "안전"
    if ratio <= 1.0:
        return "주의"
    return "경고"


def analyze(species, position, theta, h, b, L, P,
            k=DEFAULT_K, el_ratio=DEFAULT_EL_RATIO, sf_req=DEFAULT_SF):
    """한 조건에 대한 전체 해석 결과를 딕셔너리로 반환."""
    props = SPECIES[species]
    beam = BEAMS[POSITIONS[position]]

    # (1) 유효값
    E = hankinson(props["E0"], props["E90"], theta, N_E)
    F = hankinson(props["F0"], props["F90"], theta, N_F)

    # (2) 단면, 응력, 하중 단위당 처짐
    I = b * h ** 3 / 12.0
    S = b * h ** 2 / 6.0
    c_M, c_d = beam["c_M"], beam["c_d"]
    sigma = c_M * P * L / S
    delta_per_N = c_d * L ** 3 / (E * I)          # 탄성 구간의 mm/N
    K = 1.0 / delta_per_N                          # 탄성 강성 (N/mm)

    # (3) 한계 하중 (모두 하중에 비례하므로 공식으로 바로 계산)
    sigma_el = el_ratio * F
    delta_allow = beam["span_factor"] * L / k
    P_el = sigma_el * S / (c_M * L)
    P_def = delta_allow / delta_per_N
    P_sf = F * S / (sf_req * c_M * L)
    P_ult = F * S / (c_M * L)

    # (4) 이중선형 하중-처짐 곡선 (탄성 한계 이후 강성 POST_SLOPE 배)
    d_el = P_el * delta_per_N
    d_ult = d_el + (P_ult - P_el) / (POST_SLOPE * K) if P_ult > P_el else d_el

    def deflection(load):
        if load <= P_el:
            return load * delta_per_N
        return d_el + (load - P_el) / (POST_SLOPE * K)

    delta = deflection(P)

    # (5) 판정
    ratio_el = sigma / sigma_el
    ratio_def = delta / delta_allow
    sf = F / sigma
    status = {
        "elastic": _grade(ratio_el),
        "deflection": _grade(ratio_def),
        "fracture": "안전" if sf >= sf_req else ("주의" if sf >= 1.0 else "경고"),
    }
    overall = max(status.values(), key=LEVELS.index)

    limits = {"탄성 한계": P_el, "허용 처짐": P_def, f"안전율 {sf_req:g}": P_sf}
    governing = min(limits, key=limits.get)

    return {
        "beam": beam["name"], "E_eff": E, "F_eff": F, "E_ratio": E / props["E0"],
        "I": I, "S": S, "sigma": sigma, "sigma_el": sigma_el,
        "delta": delta, "delta_allow": delta_allow, "sf": sf, "sf_req": sf_req,
        "ratio_el": ratio_el, "ratio_def": ratio_def,
        "status": status, "overall": overall,
        "P_limits": limits, "P_allow": limits[governing], "governing": governing,
        "P_el": P_el, "P_ult": P_ult, "d_el": d_el, "d_ult": d_ult,
        "curve": [(0.0, 0.0), (d_el, P_el), (d_ult, P_ult)],
        "current": (delta, P),
    }


def allowable_load_by_angle(species, position, h, b, L, k=DEFAULT_K,
                            el_ratio=DEFAULT_EL_RATIO, sf_req=DEFAULT_SF, step=5):
    """각도 0~90°별 최대 허용하중 목록 [(각도, 허용하중, 지배 조건), ...]."""
    rows = []
    for ang in range(0, 91, step):
        r = analyze(species, position, ang, h, b, L, 1.0, k, el_ratio, sf_req)
        rows.append((ang, r["P_allow"], r["governing"]))
    return rows


# ---------------------------------------------------------------
# 5) 나뭇결 사진에서 각도 추정
# ---------------------------------------------------------------
def estimate_grain_angle(image, max_size=512):
    """사진의 가로 방향을 부재 길이 방향으로 보고, 결과의 기울기(0~90°)와
    판독 신뢰도(0~1)를 반환한다. 판독 불가 시 None.

    원리: 결 방향은 밝기 변화가 작고 직각 방향은 큼 -> 기울기(gradient)의
    구조 텐서로 지배 방향을 구한 뒤 90°를 더해 결 방향을 얻는다.
    """
    from PIL import Image, ImageFilter

    if not isinstance(image, Image.Image):
        image = Image.fromarray(np.asarray(image))
    gray = image.convert("L")
    gray.thumbnail((max_size, max_size))
    gray = gray.filter(ImageFilter.GaussianBlur(1.5))
    a = np.asarray(gray, dtype=float)

    gy, gx = np.gradient(a)
    jxx, jyy, jxy = (gx * gx).sum(), (gy * gy).sum(), (gx * gy).sum()
    total = jxx + jyy
    if total < 1e-9:
        return None

    phi = 0.5 * math.atan2(2 * jxy, jxx - jyy)              # 기울기 방향
    alpha = math.degrees(phi) + 90.0                         # 결 방향
    alpha = (alpha + 90.0) % 180.0 - 90.0                    # [-90, 90)로 정규화
    theta = abs(alpha)                                       # 0~90°로 접기
    coherence = math.hypot(jxx - jyy, 2 * jxy) / total       # 결의 일관성
    return theta, coherence
