import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
import json
import numpy as np
import os
import io

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

st.set_page_config(page_title="亚马逊卖家AI工具箱", layout="wide")
st.title("🎯 亚马逊卖家AI工具箱")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== Dify API 配置 =====
DIFY_BASE = "https://api.dify.ai/v1/workflows/run"
DIFY_HEADERS = {"Content-Type": "application/json"}

DIFY_选品分析_KEY = "app-M8tVPeleI3cSyIYwum1iuQQZ"
DIFY_Listing_KEY = "app-HMoMQ5y3QNWNiJ3pgWYegWwP"

# ===== 品类→英文关键词 映射（用于交叉验证）=====
品类关键词映射 = {
    '厨房收纳': ['Kitchen', 'Baking', 'Cookware', 'Food', 'Cooking', 'Bread'],
    '浴室收纳': ['Bath', 'Bathroom', 'Shower', 'Body', 'Soap', 'Toilet', 'Bath & Body'],
}

@st.cache_data
def load_niche_data():
    厨房 = pd.read_csv(os.path.join(BASE_DIR, '厨房收纳NicheSearchResults_2026_6_24.csv'), header=1)
    厨房 = 厨房.rename(columns={'客戶需求': '利基', '搜尋量 (過去 360 天)': '搜索量',
                              '平均價格 (USD)': '平均价格', '退貨率 (過去 360 天)': '退货率'})
    浴室 = pd.read_csv(os.path.join(BASE_DIR, '浴室收纳NicheSearch.csv'), header=1)
    浴室 = 浴室.rename(columns={'客戶需求': '利基', '搜尋量 (過去 360 天)': '搜索量',
                              '平均價格 (USD)': '平均价格', '退貨率 (過去 360 天)': '退货率'})
    return {'厨房收纳': 厨房, '浴室收纳': 浴室}

@st.cache_data
def load_rec_data():
    xls = pd.ExcelFile(os.path.join(BASE_DIR, '3List_of_recommendations_from_United_States_to_United_Kingdom__1_.xlsx'))
    df = pd.read_excel(xls, 'Recommendations', header=None, skiprows=4)
    cols = ['源站点', '目标站点', 'ASIN', '产品名', '子品类', '推荐原因',
            '90天销售预测$(上限)', '90天销售预测$(下限)', '90天销量(上限)', '90天销量(下限)',
            '激励', '激励过期', '广告福利', '物流方式',
            '美国站售价', '最佳销售月', '上架日期', '美国站BSR', '美国站评分',
            '英国站搜索量', '英国站点击量']
    df.columns = cols
    df['英国站搜索量'] = pd.to_numeric(df['英国站搜索量'], errors='coerce')
    df['美国站评分'] = pd.to_numeric(df['美国站评分'], errors='coerce')
    df['90天销售预测$(上限)'] = pd.to_numeric(df['90天销售预测$(上限)'], errors='coerce')
    df['美国站售价'] = pd.to_numeric(df['美国站售价'], errors='coerce')
    return df.dropna(subset=['英国站搜索量', '美国站评分', '90天销售预测$(上限)'])

niche_data = load_niche_data()
rec_data = load_rec_data()

# ===== 🎯 品类选择 =====
st.sidebar.header("🔧 设置")
选项列表 = list(niche_data.keys()) + ['📤 上传新品类CSV']
模式 = st.sidebar.selectbox("选择品类", 选项列表)

上传的数据 = None
if 模式 == '📤 上传新品类CSV':
    st.sidebar.info("💡 从亚马逊 NicheSearch 导出 CSV 上传即可分析")
    上传文件 = st.sidebar.file_uploader("选择 CSV 文件", type='csv')
    if 上传文件 is not None:
        try:
            raw_text = 上传文件.getvalue().decode('utf-8-sig')
            lines = raw_text.strip().split('\n')

            # 找表头行（含 客戶需求 的那行）
            表头行号 = None
            for idx, line in enumerate(lines):
                if '客戶需求' in line and '搜尋量' in line:
                    表头行号 = idx
                    break

            if 表头行号 is not None:
                df = pd.read_csv(io.StringIO(raw_text), header=表头行号, engine='python')
            else:
                df = pd.read_csv(io.StringIO(raw_text), header=1, engine='python')

            # 列名自动映射
            列映射 = {}
            for col in df.columns:
                col_str = str(col).strip()
                if '客戶需求' in col_str:
                    列映射[col] = '利基'
                elif col_str == '搜尋量 (過去 360 天)' or col_str == '搜尋量':
                    列映射[col] = '搜索量'
                elif '平均價格' in col_str:
                    列映射[col] = '平均价格'
                elif '退貨率' in col_str:
                    列映射[col] = '退货率'

            df = df.rename(columns=列映射)

            # 只保留需要的列
            需要的列 = [c for c in ['利基', '搜索量', '平均价格', '退货率'] if c in df.columns]
            df = df[需要的列]

            if '搜索量' not in df.columns:
                st.sidebar.error(f"❌ 没找到'搜索量'列。实际列名：{list(df.columns)}")
                st.stop()

            df['搜索量'] = pd.to_numeric(df['搜索量'], errors='coerce')
            df['平均价格'] = pd.to_numeric(df['平均价格'], errors='coerce')
            df['退货率'] = pd.to_numeric(df['退货率'], errors='coerce')
            df = df.dropna()
            上传的数据 = {'📤 ' + 上传文件.name.replace('.csv', ''): df}
            品类名 = '📤 ' + 上传文件.name.replace('.csv', '')
            st.sidebar.success(f"✅ 已加载 {len(df)} 条数据")

            # 上传的品类没有预定义关键词，用前几个利基的词推断
            上传关键词 = []
            for n in df['利基'].head(3).tolist():
                words = str(n).replace('_', ' ').replace('-', ' ').split()
                上传关键词.extend([w for w in words if len(w) > 2])
            上传关键词 = list(set(上传关键词))[:5]
            品类关键词映射['📤 ' + 上传文件.name.replace('.csv', '')] = 上传关键词 if 上传关键词 else [品类名.replace('📤 ', '')]
        except Exception as e:
            st.sidebar.error(f"❌ 读取失败：{e}")

if 上传的数据:
    品类 = 品类名
    df = 上传的数据[品类].copy()
elif 模式 == '📤 上传新品类CSV':
    st.info("👈 请在左侧边栏上传一个 NicheSearch CSV 文件")
    st.stop()
else:
    品类 = 模式
    df = niche_data[品类].copy()

# ===== ⚖️ 加权评分 =====
st.sidebar.subheader("⚖️ 权重调整")
w_搜索量 = st.sidebar.slider("搜索量权重", 0.0, 1.0, 0.4, 0.05)
w_价格 = st.sidebar.slider("价格权重", 0.0, 1.0, 0.3, 0.05)
w_退货 = st.sidebar.slider("退货率权重 (-)", 0.0, 1.0, 0.3, 0.05)

# 对数归一化
df['搜索量分'] = np.log(df['搜索量'] + 1) / np.log(df['搜索量'].max() + 1) * 100
df['价格分'] = (1 - df['平均价格'] / df['平均价格'].max()) * 100
df['退货分'] = (1 - df['退货率'] / df['退货率'].max()) * 100
df['综合得分'] = df['搜索量分'] * w_搜索量 + df['价格分'] * w_价格 + df['退货分'] * w_退货
df = df.sort_values('综合得分', ascending=False).reset_index(drop=True)

min_score = st.sidebar.slider("最低综合得分", 0, 100, 50)
max_price = st.sidebar.slider("最高价格($)", 0.0, 200.0, 100.0)
filtered = df[(df['综合得分'] >= min_score) & (df['平均价格'] <= max_price)]

top3 = filtered.head(3)

# ====================================================================
#  Tab 分页：选品分析 + Listing写作 + 以图生图（预留）
# ====================================================================
tab_names = ["🎯 选品分析", "✍️ Listing写作", "🎨 以图生图（预留）"]
tab1, tab2, tab3 = st.tabs(tab_names)

# ====================================================================
#  TAB 1：选品分析（原有全部内容）
# ====================================================================
with tab1:
    # ===== 板块1：数据概览 =====
    st.header("① 📊 数据概览")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📦 数据源", 品类)
    col2.metric("📋 利基数", len(df))
    col3.metric("💰 均价范围", f"${df['平均价格'].min():.0f} ~ ${df['平均价格'].max():.0f}")
    col4.metric("📈 搜索量范围", f"{df['搜索量'].min()//10000}万 ~ {df['搜索量'].max()//10000}万")
    with st.expander("📋 全部数据预览"):
        st.dataframe(df[['利基', '搜索量', '平均价格', '退货率', '综合得分']], width=900)

    # ===== 板块2：选品推荐 =====
    st.header("② 🏆 选品推荐")
    if len(top3) > 0:
        cols = st.columns(3)
        for i, (_, row) in enumerate(top3.iterrows()):
            with cols[i]:
                st.metric(f"#{i+1} {row['利基'][:15]}",
                          f"{row['综合得分']:.1f}分",
                          f"搜索{row['搜索量']//10000}万 | ${row['平均价格']:.0f} | 退货{row['退货率']*100:.1f}%")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"📋 结果（共{len(filtered)}条）")
        st.dataframe(filtered[['利基', '搜索量', '平均价格', '退货率', '综合得分']], width=800)
    with col2:
        st.subheader("📊 得分排行")
        if len(filtered) > 0:
            st.bar_chart(filtered.set_index('利基')['综合得分'])

    if len(filtered) > 0:
        st.subheader("📈 搜索量 vs 价格")
        fig, ax = plt.subplots(figsize=(10, 4))
        sizes = filtered['综合得分'] * 2
        sc = ax.scatter(filtered['搜索量'], filtered['平均价格'], s=sizes,
                        c=filtered['综合得分'], cmap='viridis', alpha=0.7)
        for _, row in filtered.head(10).iterrows():
            ax.annotate(row['利基'], (row['搜索量'], row['平均价格']), fontsize=7)
        ax.set_xlabel('搜索量'); ax.set_ylabel('平均价格 ($)')
        plt.colorbar(sc, ax=ax, label='综合得分')
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)

    # ===== 板块3：交叉验证 =====
    st.header("③ 🔄 交叉验证")
    关键词列表 = 品类关键词映射.get(品类, [品类.replace('收纳', '').replace('📤 ', '').strip()])
    匹配_mask = pd.Series([False] * len(rec_data))
    for kw in 关键词列表:
        if len(kw) > 1:
            匹配_mask |= rec_data['子品类'].str.contains(kw, na=False, case=False)
    匹配 = rec_data[匹配_mask]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🏪 数据源A：NicheSearch（美国站）")
        st.dataframe(top3[['利基', '搜索量', '平均价格', '综合得分']], width=450)
    with col2:
        st.subheader("📦 数据源B：美转英推荐")
        if len(匹配) > 0:
            st.dataframe(匹配[['ASIN', '子品类', '英国站搜索量', '美国站评分', '美国站售价']].head(5), width=450)
            st.caption(f"匹配关键词：{' / '.join(关键词列表)}")
        else:
            st.info("暂无匹配的ASIN推荐（子品类名称为英文，可以手动调整关键词）")
    if len(匹配) > 0 and len(top3) > 0:
        st.success("✅ **验证通过** — 美国站利基和美转英推荐有重叠品类")

    # ===== 板块4：选品核心逻辑 =====
    st.header("④ 🧠 选品核心逻辑")
    col1, col2, col3 = st.columns(3)
    with col1: st.info(f"**🔍 搜索量权重：{w_搜索量:.0%}**\n搜索量越高→需求越大")
    with col2: st.info(f"**💰 价格权重：{w_价格:.0%}**\n价格越高→利润空间越大")
    with col3: st.info(f"**📉 退货率权重：{w_退货:.0%}**（反向）\n退货率越低越好")
    with st.expander("📐 归一化公式详解"):
        st.markdown("""
**对数归一化（Log Normalization）**

```
搜索量分 = log(搜索量 + 1) / log(最大搜索量 + 1) × 100
价格分   = (1 - 平均价格 / 最高价格) × 100
退货分   = (1 - 退货率 / 最高退货率) × 100
综合得分 = 搜索量分×权重₁ + 价格分×权重₂ + 退货分×权重₃
```

**为什么用对数？** 搜索量差距几百倍时，线性归一化会让第一名吃掉所有分。
对数能把指数级差距变成线性差距。
""")

    # ===== 板块5：执行路线图 =====
    st.header("⑤ 🗺️ 执行路线图")
    if len(top3) > 0:
        首选 = top3.iloc[0]
        r2 = top3.iloc[1] if len(top3) > 1 else None
        st.subheader("🎯 建议优先上架")
        st.success(f"**🥇 {首选['利基']}** — 综合得分 {首选['综合得分']:.1f}")
        理由 = []
        if 首选['搜索量'] >= df['搜索量'].median():
            理由.append(f"✅ 搜索量({首选['搜索量']//10000}万)高于品类中位数")
        if 首选['退货率'] <= df['退货率'].median():
            理由.append(f"✅ 退货率({首选['退货率']*100:.1f}%)低于品类中位数")
        for r in 理由: st.markdown(r)
        注意事项 = []
        if 首选['平均价格'] > 40: 注意事项.append(f"⚠️ 均价${首选['平均价格']:.0f}偏高")
        if 首选['退货率'] > 0.03: 注意事项.append(f"⚠️ 退货率{首选['退货率']*100:.1f}%偏高")
        if 注意事项: st.warning("\n".join(注意事项))
        st.divider()
        st.subheader("📋 下一步行动")
        steps = [f"**① 美国站测试：** 先在 {首选['利基']} 上架1-2款产品",
                 "**② 数据验证：** 上架后跟踪搜索量变化",
                 "**③ 评估是否去英国：** 用美转英数据确认英国站搜索量",
                 "**④ 持续迭代：** 每周拉新数据，调整权重"]
        if r2 is not None: steps.append(f"**⑤ 扩展：** 稳定后考虑 {r2['利基']}")
        for s in steps: st.markdown(s)

    # ===== 🌐 汇率 =====
    st.divider()
    st.subheader("🌐 今日汇率（美→英）")
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10, proxies={"http": "", "https": ""})
        data = r.json()
        gbp = data["rates"].get("GBP", "?")
        col1, col2 = st.columns(2)
        col1.metric("💵 USD → GBP", f"1 USD = {gbp} GBP")
        col2.metric("📅 日期", data.get("date", "今天"))
    except:
        st.info("汇率加载失败（国内网络可能无法访问）")

    # ===== 🤖 Dify AI 分析 =====
    st.divider()
    st.subheader("🤖 AI 补充分析（Dify）")
    if st.button("🚀 获取AI建议"):
        with st.spinner("正在调用Dify AI分析..."):
            try:
                top3_text = "\n".join([f"- {row['利基']}：搜索量{row['搜索量']:,}，${row['平均价格']:.0f}，退货{row['退货率']*100:.1f}%，得分{row['综合得分']:.1f}" for _, row in top3.iterrows()])
                resp = requests.post(DIFY_BASE,
                    headers={"Authorization": f"Bearer {DIFY_选品分析_KEY}", "Content-Type": "application/json"},
                    json={"inputs": {"品类": 品类, "TOP3": top3_text}, "response_mode": "blocking", "user": "选品助手"},
                    timeout=60, proxies={"http": "", "https": ""})
                result = resp.json()
                if resp.status_code == 200:
                    outputs = result.get("data", {}).get("outputs", {})
                    if outputs:
                        st.success("✅ Dify 分析完成")
                        for k, v in outputs.items():
                            st.markdown(f"**{k}**：{v}")
                    else:
                        st.warning("✅ Dify 调用成功，但没有返回分析结果（可能工作流未配置完成）")
                else:
                    st.error(f"❌ Dify API 返回错误：{result}")
            except Exception as e:
                st.error(f"❌ 请求出错：{str(e)}")


# ====================================================================
#  TAB 2：Listing 写作
# ====================================================================
with tab2:
    st.header("✍️ 亚马逊 Listing 写作助手")
    st.markdown("输入产品信息，AI 自动生成亚马逊 Listing（标题、五点描述、产品描述、关键词）")

    with st.form("listing_form"):
        产品名 = st.text_input("📦 产品名", placeholder="例如：Bathroom Storage Shelves")
        卖点 = st.text_area("💡 产品卖点/描述",
                             placeholder="例如：\n- Rust-proof aluminum, no rust after 5 years\n- Easy to install in 5 minutes\n- Can hold up to 50 lbs\n- Size: 12x8x24 inches",
                             height=200)
        submitted = st.form_submit_button("🚀 生成 Listing", use_container_width=True)

    if submitted:
        if not 产品名.strip() or not 卖点.strip():
            st.warning("⚠️ 请填写产品名和产品卖点")
        else:
            with st.spinner("🤖 Dify 正在生成 Listing..."):
                try:
                    resp = requests.post(DIFY_BASE,
                        headers={"Authorization": f"Bearer {DIFY_Listing_KEY}", "Content-Type": "application/json"},
                        json={
                            "inputs": {
                                "product_name": 产品名,
                                "features": 卖点
                            },
                            "response_mode": "blocking",
                            "user": "选品助手"
                        },
                        timeout=120,
                        proxies={"http": "", "https": ""})

                    result = resp.json()
                    if resp.status_code == 200:
                        outputs = result.get("data", {}).get("outputs", {})
                        if outputs:
                            listing_text = outputs.get("result", "")
                            if listing_text:
                                st.success("✅ Listing 生成成功！")
                                st.markdown(listing_text)
                            else:
                                st.warning("✅ 调用成功但未返回内容，请检查Dify工作流的输出节点配置")
                                st.json(outputs)
                        else:
                            st.warning("⚠️ Dify 返回的 outputs 为空，可能是工作流输出节点未配置")
                            st.json(result.get("data", {}))
                    else:
                        st.error(f"❌ Dify API 返回错误：{result}")
                except Exception as e:
                    st.error(f"❌ 请求出错：{str(e)}")


# ====================================================================
#  TAB 3：以图生图（预留）
# ====================================================================
with tab3:
    st.header("🎨 以图生图（规划中）")
    st.info("""
    **功能规划中，后续会加上：**
    
    1. 📤 上传产品图片
    2. 🔄 AI 生成不同场景图（白底图、场景图、A+ 配图）
    3. 🎨 风格选择（现代、简约、手绘等）
    
    工具方案待确认（Dify + ComfyUI / 通义万相 / 即梦AI）
    """)
