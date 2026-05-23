# Setup script cho Windows PowerShell
# Chạy: .\setup.ps1 từ thư mục crypto-hybrid-bot

Write-Host "=== CRYPTO HYBRID BOT — SETUP ===" -ForegroundColor Cyan

# 1. Tạo virtual environment
Write-Host "`n[1/4] Tạo virtual environment..." -ForegroundColor Yellow
python -m venv venv
if ($LASTEXITCODE -ne 0) { Write-Host "Lỗi: Python không tìm thấy. Cài Python 3.10+ trước." -ForegroundColor Red; exit 1 }

# 2. Kích hoạt venv
Write-Host "[2/4] Kích hoạt virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# 3. Cài đặt tất cả dependencies
Write-Host "[3/4] Cài đặt dependencies..." -ForegroundColor Yellow
pip install --upgrade pip
pip install -r requirements.txt
pip install -r module_technical\requirements.txt
pip install -r module_sentiment\requirements.txt
pip install -r module_delivery\requirements.txt

# 4. Tạo file .env từ template
Write-Host "[4/4] Tạo file .env..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "✓ Đã tạo .env từ .env.example" -ForegroundColor Green
    Write-Host "  → Mở file .env và điền các API key của bạn!" -ForegroundColor Magenta
} else {
    Write-Host "  → File .env đã tồn tại, bỏ qua." -ForegroundColor Gray
}

Write-Host "`n=== SETUP HOÀN TẤT ===" -ForegroundColor Green
Write-Host "Bước tiếp theo:"
Write-Host "  1. Điền API keys vào file .env"
Write-Host "  2. Chạy SQL trong setup_db.sql trên Supabase"
Write-Host "  3. Kích hoạt venv: .\venv\Scripts\Activate.ps1"
Write-Host "  4. Test: python run_all.py"
