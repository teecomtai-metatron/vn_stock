import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import math
from streamlit_gsheets import GSheetsConnection

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="Hệ thống Quản trị & DCA Chứng khoán", layout="wide", page_icon="📈")

# --- KẾT NỐI GOOGLE SHEETS ---
# Yêu cầu file secrets.toml phải được cấu hình đúng
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Chưa cấu hình kết nối Google Sheets. Vui lòng kiểm tra file secrets.toml.")
    st.stop()

# --- HÀM QUẢN LÝ DỮ LIỆU ĐÁM MÂY ---
def load_data():
    try:
        # ttl=0 để luôn lấy dữ liệu mới nhất, không dùng cache cũ
        df = conn.read(worksheet="Sheet1", ttl=0)
        # Nếu sheet trống hoặc mất định dạng, khởi tạo lại các cột chuẩn
        if df.empty or "Mã CK" not in df.columns:
            return pd.DataFrame(columns=["Ngày", "Mã CK", "Loại lệnh", "Giá (VNĐ)", "Khối lượng"])
        return df.dropna(subset=["Mã CK"]) # Bỏ các dòng trống
    except Exception:
        return pd.DataFrame(columns=["Ngày", "Mã CK", "Loại lệnh", "Giá (VNĐ)", "Khối lượng"])

def save_data(df):
    """Ghi đè toàn bộ DataFrame mới lên Google Sheets"""
    conn.update(worksheet="Sheet1", data=df)

def calculate_portfolio(df, ticker):
    """Tính tự động khối lượng và giá vốn trung bình dựa trên lịch sử"""
    df_ticker = df[df["Mã CK"] == ticker].copy()
    
    total_qty = 0
    avg_price = 0.0
    
    for idx, row in df_ticker.iterrows():
        qty = float(row['Khối lượng'])
        price = float(row['Giá (VNĐ)'])
        
        if row['Loại lệnh'] == 'Mua':
            new_qty = total_qty + qty
            avg_price = ((avg_price * total_qty) + (price * qty)) / new_qty
            total_qty = new_qty
        elif row['Loại lệnh'] == 'Bán':
            total_qty -= qty
            if total_qty <= 0:
                total_qty = 0
                avg_price = 0.0
                
    return total_qty, avg_price

# --- HÀM LẤY GIÁ REAL-TIME ---
@st.cache_data(ttl=60)
def get_current_price(ticker):
    sources = ['TCBS', 'VCI', 'SSI', 'DNSE']
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    for src in sources:
        try:
            stock = Vnstock().stock(symbol=ticker, source=src)
            df_hist = stock.quote.history(start=start_date, end=end_date, interval='1D')
            if not df_hist.empty and 'close' in df_hist.columns:
                price = df_hist.iloc[-1]['close']
                if 0 < price < 1000:
                    return float(price * 1000)
                return float(price)
        except Exception:
            continue
    return 0.0

# --- LOAD DỮ LIỆU TỪ MÂY ---
with st.spinner('Đang đồng bộ dữ liệu từ Google Sheets...'):
    df_history = load_data()

# ==========================================
# SIDEBAR: NHẬP LỆNH & CÀI ĐẶT
# ==========================================
with st.sidebar:
    st.header("📝 Ghi lịch sử giao dịch")
    with st.form("nhap_lenh_form", clear_on_submit=True):
        ma_ck_moi = st.text_input("Mã CK (VD: HPG)").upper()
        loai_lenh = st.selectbox("Loại lệnh", ["Mua", "Bán"])
        gia_nhap = st.number_input("Giá khớp (VNĐ)", min_value=0.0, step=100.0)
        kl_nhap = st.number_input("Khối lượng", min_value=0, step=100)
        ngay_gd = st.date_input("Ngày giao dịch")
        
        submit = st.form_submit_button("Lưu lệnh (Đồng bộ lên mây)")
        
        if submit and ma_ck_moi and kl_nhap > 0:
            new_row = pd.DataFrame([{
                "Ngày": ngay_gd.strftime('%Y-%m-%d'), 
                "Mã CK": ma_ck_moi, 
                "Loại lệnh": loai_lenh, 
                "Giá (VNĐ)": gia_nhap, 
                "Khối lượng": kl_nhap
            }])
            df_history = pd.concat([df_history, new_row], ignore_index=True)
            save_data(df_history) # Ghi thẳng lên Google Sheets
            st.success(f"Đã lưu {loai_lenh} {ma_ck_moi} lên Google Sheets!")
            st.rerun()
    
    st.divider()
    st.header("⚙️ Cài đặt chung")
    fee_pct = st.slider("Phí giao dịch + Thuế (%)", 0.0, 1.0, 0.25, step=0.05) / 100

# ==========================================
# GIAO DIỆN CHÍNH: THỐNG KÊ DANH MỤC
# ==========================================
st.title("☁️ Bảng điều khiển Danh mục (Cloud DB)")

list_tickers = df_history["Mã CK"].unique().tolist()
if not list_tickers:
    st.info("👈 Chào mừng! Database của bạn đang trống. Hãy nhập lệnh đầu tiên!")
    st.stop()

selected_ticker = st.selectbox("📌 Chọn mã chứng khoán để phân tích:", list_tickers)

# Tính toán các thông số
hist_qty, hist_price = calculate_portfolio(df_history, selected_ticker)
curr_price = get_current_price(selected_ticker)

if curr_price == 0:
    curr_price = st.number_input(f"Nhập tay giá {selected_ticker} hiện tại (do lỗi API)", value=float(hist_price), step=100.0)

total_cost = hist_price * hist_qty
market_value = curr_price * hist_qty
pnl = market_value - total_cost - (market_value * fee_pct) 
pnl_pct = (pnl / total_cost) * 100 if total_cost > 0 else 0

st.divider()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Giá thị trường (Real-time)", f"{curr_price:,.0f} đ")
col2.metric("Giá vốn trung bình", f"{hist_price:,.0f} đ")
col3.metric("Số lượng đang giữ", f"{hist_qty:,.0f} CP")
col4.metric("Lời/Lỗ tạm tính", f"{pnl:,.0f} đ", f"{pnl_pct:.2f}%")

if hist_qty == 0:
    st.warning("Bạn hiện không nắm giữ mã này (Đã bán hết). Mua thêm để kích hoạt tính năng DCA.")
    st.stop()

st.divider()

# ==========================================
# TÍNH NĂNG 2: TÍNH NGƯỢC DCA (GOAL-SEEK)
# ==========================================
st.header("🎯 2. Lên kế hoạch Xuống tiền (Tính toán tự động)")
st.markdown("Phần mềm sẽ tự giải phương trình để tìm ra **Khối lượng** và **Số tiền** cần nạp dựa trên mục tiêu chốt lời của bạn.")

with st.form("dca_reverse_form"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        target_profit_pct = st.number_input("% Lãi kỳ vọng trên TỔNG vốn (VD: Nhập 5 cho 5%)", value=2.0, step=0.5) / 100
    with col_b:
        target_sell_price = st.number_input("Giá dự kiến chốt lời (VNĐ)", value=float(hist_price), step=100.0)
    with col_c:
        dca_buy_price = st.number_input("Giá mua bắt đáy hiện tại (VNĐ)", value=float(curr_price), step=100.0)

    calc_submit = st.form_submit_button("Lập kế hoạch giải ngân 🚀")

if calc_submit:
    # Công thức Goal-Seek
    numerator = hist_qty * (hist_price * (1 + target_profit_pct) - target_sell_price)
    denominator = target_sell_price - dca_buy_price * (1 + target_profit_pct)
    
    if denominator <= 0:
        st.error(f"❌ **Mục tiêu phi thực tế!** \n\nVới mức giá bắt đáy {dca_buy_price:,.0f}đ và đòi hỏi lãi {target_profit_pct*100}%, giá chốt lời phải lớn hơn {(dca_buy_price * (1 + target_profit_pct)):,.0f}đ.")
    else:
        q_new = numerator / denominator
        
        if q_new <= 0:
            st.success("✅ **Không cần nạp thêm tiền!** Với khối lượng và giá vốn hiện tại, nếu thị trường lên mức chốt lời kia, bạn đã tự động đạt (hoặc vượt) mức % lãi mong muốn rồi.")
        else:
            # Làm tròn lô 100 cổ phiếu (Chuẩn chứng khoán VN)
            q_new_rounded = math.ceil(q_new / 100) * 100 
            required_capital = q_new_rounded * dca_buy_price
            
            new_avg_proof = (hist_qty * hist_price + q_new_rounded * dca_buy_price) / (hist_qty + q_new_rounded)
            
            st.success(f"🔥 **CHỈ LỆNH THỰC THI CHO MÃ {selected_ticker}:**")
            st.markdown(f"""
            * Khối lượng cần mua thêm (Bắt đáy): **{q_new_rounded:,}** Cổ phiếu
            * Dòng tiền cần chuẩn bị nạp vào: **{required_capital:,.0f} VNĐ**
            """)
            
            st.info(f"""
            **💡 Giải thích dòng tiền:**
            Nếu bạn nạp **{required_capital:,.0f}đ** để mua thêm **{q_new_rounded:,}** cổ phiếu giá **{dca_buy_price:,.0f}đ**:
            1. Giá vốn trung bình mới của bạn sẽ rớt xuống: **{new_avg_proof:,.0f} đ/CP**.
            2. Chờ đợi thị trường phục hồi lên đúng **{target_sell_price:,.0f} đ**, bạn đặt lệnh Bán Toàn Bộ.
            3. Bạn sẽ thu về đúng **{target_profit_pct * 100}%** lợi nhuận (trên tổng gốc cũ + gốc mới)!
            """)

st.divider()

# ==========================================
# QUẢN LÝ & XÓA LỊCH SỬ GIAO DỊCH
# ==========================================
with st.expander("👁️ Quản lý & Xóa Lịch sử Giao dịch", expanded=False):
    if not df_history.empty:
        # Hiển thị bảng dữ liệu
        st.dataframe(df_history, use_container_width=True)
        
        st.markdown("### 🗑️ Xóa lệnh giao dịch (Hủy bỏ)")
        
        # Tạo danh sách các lệnh để người dùng chọn xóa
        delete_options = []
        for idx, row in df_history.iterrows():
            delete_options.append(f"Dòng {idx} | Ngày {row['Ngày']} | {row['Loại lệnh']} {row['Khối lượng']} CP {row['Mã CK']} | Giá: {row['Giá (VNĐ)']}")
            
        selected_to_delete = st.selectbox("Chọn lệnh bạn nhập sai hoặc muốn hủy bỏ:", delete_options)
        
        if st.button("❌ Xóa lệnh này"):
            # Lấy index của dòng cần xóa (từ chuỗi text đã chọn)
            idx_to_delete = int(selected_to_delete.split(" |")[0].replace("Dòng ", ""))
            
            # Xóa dòng đó khỏi DataFrame và lưu lại
            df_history = df_history.drop(idx_to_delete).reset_index(drop=True)
            df_history.to_csv(DATA_FILE, index=False)
            
            st.success("Đã xóa lệnh thành công! Hệ thống đang tải lại số liệu...")
            st.rerun() # Refresh app để tính lại giá vốn ngay lập tức
    else:
        st.write("Chưa có lịch sử giao dịch nào.")
