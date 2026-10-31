"""app.py - 목재 휨·안전성 시뮬레이터 화면 (실행: streamlit run app.py)

화면(app.py)과 계산(core.py)을 분리했다.
 - 기능 1: 조건 입력·입력 검증·나뭇결 각도 도출
 - 기능 2: 행킨슨(Hankinson) 식, 응력·처짐 계산 (결과는 st.session_state에 임시 저장)
 - 기능 3: 안전성 판정 배지, 하중-처짐 그래프, 최대 허용하중
"""
import matplotlib.pyplot as plt
import streamlit as st
from PIL import Image

import core

# 그래프 한글 폰트 (윈도우: 맑은 고딕, 맥: AppleGothic, 리눅스: 나눔고딕). 없으면 기본 폰트.
plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title="목재 휨·안전성 시뮬레이터", layout="wide")
st.title("목재 휨·안전성 시뮬레이터")
st.caption("나뭇결 각도 및 조건별 처짐·파괴 진단 (집중하중 기준, 물성값은 임시값)")
st.caption("※ 교육·참고용 계산입니다. 실제 시공·구조 안전 판단은 구조기술자 검토와 공인 설계기준이 필요합니다.")

BADGE = {"안전": st.success, "주의": st.warning, "경고": st.error}

if "result" not in st.session_state:
    st.session_state["result"] = None
if "theta" not in st.session_state:
    st.session_state["theta"] = 0

left, right = st.columns([1, 1.4])

# ---------------------------------------------------------------
# 왼쪽: 조건 입력 영역 (기능 1)
# ---------------------------------------------------------------
with left:
    st.subheader("조건 입력 영역")
    position = st.selectbox("적용 위치", list(core.POSITIONS))
    species = st.selectbox("수종 선택", list(core.SPECIES))

    mode = st.radio("나뭇결 각도 입력 방식", ["직접 입력(슬라이더)", "나뭇결 사진으로 추정"],
                    horizontal=True)
    if mode == "나뭇결 사진으로 추정":
        st.caption("사진의 가로 방향이 부재의 길이 방향이라고 가정합니다.")
        photo = st.file_uploader("나뭇결 사진", type=["png", "jpg", "jpeg"])
        if photo is not None:
            try:
                image = Image.open(photo)
                st.image(image, width=260)
                signature = f"{photo.name}-{photo.size}"
                if st.session_state.get("photo_sig") != signature:
                    est = core.estimate_grain_angle(image)
                    st.session_state["photo_sig"] = signature
                    st.session_state["photo_est"] = est
                    if est is not None:
                        st.session_state["theta"] = int(round(est[0]))
                est = st.session_state.get("photo_est")
                if est is None:
                    st.warning("결을 판독하지 못했습니다. 아래 슬라이더로 직접 입력하세요.")
                elif est[1] < 0.3:
                    st.warning(f"추정 {est[0]:.1f}° (신뢰도 {est[1]:.2f}): 결이 불분명합니다. "
                               "슬라이더로 직접 확인·수정하세요.")
                else:
                    st.info(f"추정 각도 {est[0]:.1f}° (신뢰도 {est[1]:.2f}). 필요하면 아래에서 수정하세요.")
            except Exception:
                st.error("이미지를 열 수 없습니다. 다른 파일을 올리거나 각도를 직접 입력하세요.")

    theta = st.slider("나뭇결 각도 (°)", 0, 90, key="theta")

    h_txt = st.text_input("부재 두께 h (mm)", "45")
    b_txt = st.text_input("부재 폭 b (mm)", "90")
    L_txt = st.text_input("부재 경간 L (mm)", "900")
    P_txt = st.text_input("작용 하중 P (N, 집중하중)", "500")

    with st.expander("판정 기준 (기본값 변경 가능)"):
        k = st.number_input("허용처짐 = L/k (외팔보는 2L/k)", 50, 1000, core.DEFAULT_K)
        el_ratio = st.number_input("탄성 한계 비율 (휨강도 대비)", 0.1, 1.0, core.DEFAULT_EL_RATIO, 0.05)
        sf_req = st.number_input("요구 안전율", 1.0, 5.0, core.DEFAULT_SF, 0.1)

    run = st.button("진단 및 그래프 생성")

# ---------------------------------------------------------------
# 버튼 처리: 검증 -> 계산 -> 저장 (기능 1, 2)
# ---------------------------------------------------------------
if run:
    values, errors, warnings = core.validate_inputs(
        {"h": h_txt, "b": b_txt, "L": L_txt, "P": P_txt, "theta": theta})
    if errors:
        st.session_state["result"] = None
        with right:
            for e in errors:
                st.error(e)
            st.info("입력을 고친 뒤 다시 '진단 및 그래프 생성'을 눌러 주세요.")
        st.stop()
    result = core.analyze(species, position, values["theta"], values["h"], values["b"],
                          values["L"], values["P"], k, el_ratio, sf_req)
    st.session_state["result"] = {
        "r": result, "warnings": warnings, "values": values,
        "species": species, "position": position, "k": k,
        "el_ratio": el_ratio, "sf_req": sf_req,
    }

# ---------------------------------------------------------------
# 오른쪽: 결과 (기능 3)
# ---------------------------------------------------------------
with right:
    saved = st.session_state["result"]
    if saved is None:
        st.info("왼쪽에 조건을 입력하고 '진단 및 그래프 생성'을 누르세요.")
    else:
        r, v = saved["r"], saved["values"]
        for w in saved["warnings"]:
            st.warning(w)

        st.subheader("진단 결과")
        BADGE[r["overall"]](f"종합 판정: {r['overall']}  ({r['beam']}, {saved['species']}, 각도 {v['theta']:g}°)")
        c1, c2, c3 = st.columns(3)
        with c1:
            BADGE[r["status"]["elastic"]](f"탄성 영역: {r['status']['elastic']}")
            st.caption(f"응력 {r['sigma']:.2f} / 탄성 한계 {r['sigma_el']:.2f} MPa")
        with c2:
            BADGE[r["status"]["deflection"]](f"허용 처짐: {r['status']['deflection']}")
            st.caption(f"처짐 {r['delta']:.2f} / 허용 {r['delta_allow']:.2f} mm")
        with c3:
            BADGE[r["status"]["fracture"]](f"파괴 안전: {r['status']['fracture']}")
            st.caption(f"안전율 {r['sf']:.2f} (요구 {r['sf_req']:g} 이상)")

        m1, m2, m3 = st.columns(3)
        m1.metric("유효탄성계수 E", f"{r['E_eff']:,.0f} MPa", f"E0 대비 {r['E_ratio']*100:.0f}%")
        m2.metric("유효 휨강도", f"{r['F_eff']:.1f} MPa")
        m3.metric("최대 허용하중", f"{r['P_allow']:,.0f} N", f"지배 조건: {r['governing']}", delta_color="off")

        # 하중-처짐 그래프
        fig, ax = plt.subplots(figsize=(6, 3.8))
        xs, ys = zip(*r["curve"])
        ax.plot(xs, ys, color="#2f6f4f", lw=2, label="하중-처짐 곡선(이중선형 가정)")
        ax.scatter([r["current"][0]], [r["current"][1]], color="#d9480f", zorder=3, label="현재 하중")
        ax.axvline(r["delta_allow"], color="#868e96", ls="--", label="허용 처짐")
        ax.axhline(r["P_allow"], color="#1c7ed6", ls=":", label="최대 허용하중")
        ax.set_xlabel("deflection (mm)")
        ax.set_ylabel("load (N)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        st.pyplot(fig)
        plt.close(fig)
        st.caption("탄성 한계 이후 곡선은 참고용 추정입니다 (목재 휨 파괴는 취성적).")

        with st.expander("각도별 최대 허용하중 (각도-성능 지도)"):
            rows = core.allowable_load_by_angle(saved["species"], saved["position"], v["h"], v["b"],
                                                v["L"], saved["k"], saved["el_ratio"], saved["sf_req"])
            fig2, ax2 = plt.subplots(figsize=(6, 3))
            ax2.plot([a for a, _, _ in rows], [p for _, p, _ in rows], marker="o", color="#2f6f4f")
            ax2.set_xlabel("grain angle (deg)")
            ax2.set_ylabel("allowable load (N)")
            ax2.grid(alpha=0.3)
            st.pyplot(fig2)
            plt.close(fig2)

        with st.expander("계산 가정과 한계"):
            st.markdown(
                "- 물성값(E0, E90, F0, F90)은 임시값이며 출처 확인 후 교체 예정입니다.\n"
                "- 부재 전체의 결 방향이 θ로 일정하고, 실내 건조 상태라고 가정합니다.\n"
                "- 전단변형, 크리프, 측면 좌굴, 옹이·결함은 고려하지 않습니다.\n"
                "- 하중은 보 중앙(외팔보는 끝단)의 집중하중입니다.\n"
                "- 탄성 한계 이후는 강성이 20%로 줄어드는 이중선형 가정입니다.")
