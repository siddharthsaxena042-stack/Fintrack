import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Application configuration loaded from environment variables."""

    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "fintrack-dev-secret-key-change-in-prod")
    _db_env = os.environ.get("DATABASE_PATH", "fintrack.db")
    DATABASE_PATH = str(Path(_db_env) if Path(_db_env).is_absolute() else BASE_DIR / _db_env)
    UPSTOX_ACCESS_TOKEN = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    UPSTOX_API_BASE = os.environ.get("UPSTOX_API_BASE", "https://api.upstox.com/v3").rstrip("/")
    MARKET_STREAM_INTERVAL = max(1, int(os.environ.get("MARKET_STREAM_INTERVAL", "2")))
    DEFAULT_VIRTUAL_BALANCE = 100000.00
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


EXPENSE_CATEGORIES = [
    "Food",
    "Travel",
    "Bills",
    "Shopping",
    "Entertainment",
    "Healthcare",
    "Housing",
    "Education",
    "Other",
]


NSE_INSTRUMENTS = {
    "RELIANCE": {
        "symbol": "RELIANCE",
        "name": "Reliance Industries Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE002A01018",
        "yf_symbol": "RELIANCE.NS",
        "sector": "Energy & Petrochemicals",
        "ref_price": 1295.40,
        "volatility": 0.0022,
    },
    "TCS": {
        "symbol": "TCS",
        "name": "Tata Consultancy Services Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE467B01029",
        "yf_symbol": "TCS.NS",
        "sector": "Information Technology",
        "ref_price": 4148.75,
        "volatility": 0.0018,
    },
    "HDFCBANK": {
        "symbol": "HDFCBANK",
        "name": "HDFC Bank Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE040A01034",
        "yf_symbol": "HDFCBANK.NS",
        "sector": "Banking & Finance",
        "ref_price": 1742.60,
        "volatility": 0.0019,
    },
    "INFY": {
        "symbol": "INFY",
        "name": "Infosys Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE009A01021",
        "yf_symbol": "INFY.NS",
        "sector": "Information Technology",
        "ref_price": 1885.20,
        "volatility": 0.0021,
    },
    "ICICIBANK": {
        "symbol": "ICICIBANK",
        "name": "ICICI Bank Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE090A01021",
        "yf_symbol": "ICICIBANK.NS",
        "sector": "Banking & Finance",
        "ref_price": 1298.90,
        "volatility": 0.0020,
    },
    "SBIN": {
        "symbol": "SBIN",
        "name": "State Bank of India",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE062A01020",
        "yf_symbol": "SBIN.NS",
        "sector": "Banking & Finance",
        "ref_price": 828.45,
        "volatility": 0.0025,
    },
    "TATAMOTORS": {
        "symbol": "TATAMOTORS",
        "name": "Tata Motors Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE155A01022",
        "yf_symbol": "TATAMOTORS.NS",
        "sector": "Automobile",
        "ref_price": 786.30,
        "volatility": 0.0028,
    },
    "NIFTY 50": {
        "symbol": "NIFTY 50",
        "name": "NSE Nifty 50 Index",
        "exchange": "NSE",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "yf_symbol": "^NSEI",
        "sector": "Benchmark Index",
        "ref_price": 24180.50,
        "volatility": 0.0012,
    },
    "ITC": {
        "symbol": "ITC",
        "name": "ITC Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE154A01025",
        "yf_symbol": "ITC.NS",
        "sector": "FMCG",
        "ref_price": 476.80,
        "volatility": 0.0016,
    },
    "BHARTIARTL": {
        "symbol": "BHARTIARTL",
        "name": "Bharti Airtel Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE397D01024",
        "yf_symbol": "BHARTIARTL.NS",
        "sector": "Telecom",
        "ref_price": 1582.15,
        "volatility": 0.0022,
    },
    "KOTAKBANK": {
        "symbol": "KOTAKBANK",
        "name": "Kotak Mahindra Bank Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE237A01028",
        "yf_symbol": "KOTAKBANK.NS",
        "sector": "Banking & Finance",
        "ref_price": 1765.00,
        "volatility": 0.0020,
    },
    "LT": {
        "symbol": "LT",
        "name": "Larsen & Toubro Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE018A01030",
        "yf_symbol": "LT.NS",
        "sector": "Infrastructure",
        "ref_price": 3624.50,
        "volatility": 0.0023,
    },
    "AXISBANK": {
        "symbol": "AXISBANK",
        "name": "Axis Bank Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE238A01034",
        "yf_symbol": "AXISBANK.NS",
        "sector": "Banking & Finance",
        "ref_price": 1148.25,
        "volatility": 0.0023,
    },
    "BAJFINANCE": {
        "symbol": "BAJFINANCE",
        "name": "Bajaj Finance Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE296A01024",
        "yf_symbol": "BAJFINANCE.NS",
        "sector": "Financial Services",
        "ref_price": 6742.80,
        "volatility": 0.0026,
    },
    "WIPRO": {
        "symbol": "WIPRO",
        "name": "Wipro Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE075A01022",
        "yf_symbol": "WIPRO.NS",
        "sector": "Information Technology",
        "ref_price": 568.90,
        "volatility": 0.0021,
    },
    "MARUTI": {
        "symbol": "MARUTI",
        "name": "Maruti Suzuki India Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE585B01010",
        "yf_symbol": "MARUTI.NS",
        "sector": "Automobile",
        "ref_price": 11240.00,
        "volatility": 0.0019,
    },
    "SUNPHARMA": {
        "symbol": "SUNPHARMA",
        "name": "Sun Pharmaceutical Industries Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE044A01036",
        "yf_symbol": "SUNPHARMA.NS",
        "sector": "Pharmaceuticals",
        "ref_price": 1812.60,
        "volatility": 0.0020,
    },
    "TITAN": {
        "symbol": "TITAN",
        "name": "Titan Company Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE280A01028",
        "yf_symbol": "TITAN.NS",
        "sector": "Consumer Discretionary",
        "ref_price": 3295.75,
        "volatility": 0.0022,
    },
    "ASIANPAINT": {
        "symbol": "ASIANPAINT",
        "name": "Asian Paints Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE021A01026",
        "yf_symbol": "ASIANPAINT.NS",
        "sector": "Consumer Goods",
        "ref_price": 2486.40,
        "volatility": 0.0021,
    },
    "HINDUNILVR": {
        "symbol": "HINDUNILVR",
        "name": "Hindustan Unilever Ltd.",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE030A01027",
        "yf_symbol": "HINDUNILVR.NS",
        "sector": "FMCG",
        "ref_price": 2412.10,
        "volatility": 0.0015,
    },
}

DEFAULT_WATCHLIST_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "TATAMOTORS", "NIFTY 50"]
