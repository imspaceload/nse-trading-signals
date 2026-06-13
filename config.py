import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# Each symbol has:
#   yf   - Yahoo Finance ticker (for data fetching / indicators)
#   nse  - NSE symbol (for option chain via nsepython)
#   tv   - TradingView widget symbol (for live chart)
SYMBOLS = {
    # ── Indices ──
    "NIFTY 50":         {"yf": "^NSEI",           "nse": "NIFTY",       "tv": "NSE:NIFTY50"},
    "BANK NIFTY":       {"yf": "^NSEBANK",        "nse": "BANKNIFTY",   "tv": "NSE:BANKNIFTY"},
    "FIN NIFTY":        {"yf": "^CNXFIN",         "nse": "FINNIFTY",    "tv": "NSE:FINNIFTY"},
    "MIDCAP SELECT":    {"yf": "^NSEMDCP50",      "nse": "MIDCPNIFTY",  "tv": "NSE:MIDCPNIFTY"},
    "SENSEX":           {"yf": "^BSESN",          "nse": "",            "tv": "BSE:SENSEX"},
    "INDIA VIX":        {"yf": "^INDIAVIX",       "nse": "",            "tv": "NSE:INDIAVIX"},
    # ── Commodities ──
    "MCX CRUDE OIL":    {"yf": "CL=F",            "nse": "",            "tv": "MCX:CRUDEOIL1!"},
    "MCX NATURAL GAS":  {"yf": "NG=F",            "nse": "",            "tv": "MCX:NATURALGAS1!"},
    "MCX GOLD":         {"yf": "GC=F",            "nse": "",            "tv": "MCX:GOLD1!"},
    "MCX SILVER":       {"yf": "SI=F",            "nse": "",            "tv": "MCX:SILVER1!"},
    # ── NIFTY 50 Stocks ──
    "RELIANCE":         {"yf": "RELIANCE.NS",     "nse": "RELIANCE",    "tv": "NSE:RELIANCE"},
    "TCS":              {"yf": "TCS.NS",          "nse": "TCS",         "tv": "NSE:TCS"},
    "INFOSYS":          {"yf": "INFY.NS",         "nse": "INFY",        "tv": "NSE:INFY"},
    "HDFC BANK":        {"yf": "HDFCBANK.NS",     "nse": "HDFCBANK",    "tv": "NSE:HDFCBANK"},
    "ICICI BANK":       {"yf": "ICICIBANK.NS",    "nse": "ICICIBANK",   "tv": "NSE:ICICIBANK"},
    "SBIN":             {"yf": "SBIN.NS",         "nse": "SBIN",        "tv": "NSE:SBIN"},
    "TATAMOTORS":       {"yf": "TATAMOTORS.NS",   "nse": "TATAMOTORS",  "tv": "NSE:TATAMOTORS"},
    "ITC":              {"yf": "ITC.NS",          "nse": "ITC",         "tv": "NSE:ITC"},
    "WIPRO":            {"yf": "WIPRO.NS",        "nse": "WIPRO",       "tv": "NSE:WIPRO"},
    "ADANIENT":         {"yf": "ADANIENT.NS",     "nse": "ADANIENT",    "tv": "NSE:ADANIENT"},
    "BHARTIARTL":       {"yf": "BHARTIARTL.NS",   "nse": "BHARTIARTL",  "tv": "NSE:BHARTIARTL"},
    "HCLTECH":          {"yf": "HCLTECH.NS",      "nse": "HCLTECH",     "tv": "NSE:HCLTECH"},
    "KOTAKBANK":        {"yf": "KOTAKBANK.NS",    "nse": "KOTAKBANK",   "tv": "NSE:KOTAKBANK"},
    "LT":               {"yf": "LT.NS",           "nse": "LT",          "tv": "NSE:LT"},
    "MARUTI":           {"yf": "MARUTI.NS",       "nse": "MARUTI",      "tv": "NSE:MARUTI"},
    "SUNPHARMA":        {"yf": "SUNPHARMA.NS",    "nse": "SUNPHARMA",   "tv": "NSE:SUNPHARMA"},
    "AXISBANK":         {"yf": "AXISBANK.NS",     "nse": "AXISBANK",    "tv": "NSE:AXISBANK"},
    "BAJFINANCE":       {"yf": "BAJFINANCE.NS",   "nse": "BAJFINANCE",  "tv": "NSE:BAJFINANCE"},
    "BAJAJFINSV":       {"yf": "BAJAJFINSV.NS",   "nse": "BAJAJFINSV",  "tv": "NSE:BAJAJFINSV"},
    "TITAN":            {"yf": "TITAN.NS",        "nse": "TITAN",       "tv": "NSE:TITAN"},
    "ASIANPAINT":       {"yf": "ASIANPAINT.NS",   "nse": "ASIANPAINT",  "tv": "NSE:ASIANPAINT"},
    "NESTLEIND":        {"yf": "NESTLEIND.NS",    "nse": "NESTLEIND",   "tv": "NSE:NESTLEIND"},
    "ULTRACEMCO":       {"yf": "ULTRACEMCO.NS",   "nse": "ULTRACEMCO",  "tv": "NSE:ULTRACEMCO"},
    "POWERGRID":        {"yf": "POWERGRID.NS",    "nse": "POWERGRID",   "tv": "NSE:POWERGRID"},
    "NTPC":             {"yf": "NTPC.NS",         "nse": "NTPC",        "tv": "NSE:NTPC"},
    "ONGC":             {"yf": "ONGC.NS",         "nse": "ONGC",        "tv": "NSE:ONGC"},
    "JSWSTEEL":         {"yf": "JSWSTEEL.NS",     "nse": "JSWSTEEL",    "tv": "NSE:JSWSTEEL"},
    "TATASTEEL":        {"yf": "TATASTEEL.NS",    "nse": "TATASTEEL",   "tv": "NSE:TATASTEEL"},
    "TECHM":            {"yf": "TECHM.NS",        "nse": "TECHM",       "tv": "NSE:TECHM"},
    "HINDALCO":         {"yf": "HINDALCO.NS",     "nse": "HINDALCO",    "tv": "NSE:HINDALCO"},
    "INDUSINDBK":       {"yf": "INDUSINDBK.NS",   "nse": "INDUSINDBK",  "tv": "NSE:INDUSINDBK"},
    "DIVISLAB":         {"yf": "DIVISLAB.NS",     "nse": "DIVISLAB",    "tv": "NSE:DIVISLAB"},
    "DRREDDY":          {"yf": "DRREDDY.NS",      "nse": "DRREDDY",     "tv": "NSE:DRREDDY"},
    "CIPLA":            {"yf": "CIPLA.NS",        "nse": "CIPLA",       "tv": "NSE:CIPLA"},
    "APOLLOHOSP":       {"yf": "APOLLOHOSP.NS",   "nse": "APOLLOHOSP",  "tv": "NSE:APOLLOHOSP"},
    "EICHERMOT":        {"yf": "EICHERMOT.NS",    "nse": "EICHERMOT",   "tv": "NSE:EICHERMOT"},
    "HEROMOTOCO":       {"yf": "HEROMOTOCO.NS",   "nse": "HEROMOTOCO",  "tv": "NSE:HEROMOTOCO"},
    "M&M":              {"yf": "M&M.NS",          "nse": "M&M",         "tv": "NSE:M_M"},
    "TATACONSUM":       {"yf": "TATACONSUM.NS",   "nse": "TATACONSUM",  "tv": "NSE:TATACONSUM"},
    "LTIM":             {"yf": "LTIM.NS",         "nse": "LTIM",        "tv": "NSE:LTIM"},
    "COALINDIA":        {"yf": "COALINDIA.NS",    "nse": "COALINDIA",   "tv": "NSE:COALINDIA"},
    "BPCL":             {"yf": "BPCL.NS",         "nse": "BPCL",        "tv": "NSE:BPCL"},
    "GRASIM":           {"yf": "GRASIM.NS",       "nse": "GRASIM",      "tv": "NSE:GRASIM"},
    "HDFCLIFE":         {"yf": "HDFCLIFE.NS",     "nse": "HDFCLIFE",    "tv": "NSE:HDFCLIFE"},
    "SBILIFE":          {"yf": "SBILIFE.NS",      "nse": "SBILIFE",     "tv": "NSE:SBILIFE"},
    "BAJAJ-AUTO":       {"yf": "BAJAJ-AUTO.NS",   "nse": "BAJAJ-AUTO",  "tv": "NSE:BAJAJ_AUTO"},
    "BRITANNIA":        {"yf": "BRITANNIA.NS",    "nse": "BRITANNIA",   "tv": "NSE:BRITANNIA"},
    "SHRIRAMFIN":       {"yf": "SHRIRAMFIN.NS",   "nse": "SHRIRAMFIN",  "tv": "NSE:SHRIRAMFIN"},
    # Popular F&O stocks
    "IDEA":             {"yf": "IDEA.NS",         "nse": "IDEA",        "tv": "NSE:IDEA"},
    "TATAPOWER":        {"yf": "TATAPOWER.NS",    "nse": "TATAPOWER",   "tv": "NSE:TATAPOWER"},
    "ZOMATO":           {"yf": "ZOMATO.NS",       "nse": "ZOMATO",      "tv": "NSE:ZOMATO"},
    "IRCTC":            {"yf": "IRCTC.NS",        "nse": "IRCTC",       "tv": "NSE:IRCTC"},
    "PNB":              {"yf": "PNB.NS",          "nse": "PNB",         "tv": "NSE:PNB"},
    "BANKBARODA":       {"yf": "BANKBARODA.NS",   "nse": "BANKBARODA",  "tv": "NSE:BANKBARODA"},
    "VEDL":             {"yf": "VEDL.NS",         "nse": "VEDL",        "tv": "NSE:VEDL"},
    "TATACOMM":         {"yf": "TATACOMM.NS",     "nse": "TATACOMM",    "tv": "NSE:TATACOMM"},
    "DLF":              {"yf": "DLF.NS",          "nse": "DLF",         "tv": "NSE:DLF"},
    "IDFCFIRSTB":       {"yf": "IDFCFIRSTB.NS",   "nse": "IDFCFIRSTB",  "tv": "NSE:IDFCFIRSTB"},
    "BHEL":             {"yf": "BHEL.NS",         "nse": "BHEL",        "tv": "NSE:BHEL"},
    "SAIL":             {"yf": "SAIL.NS",         "nse": "SAIL",        "tv": "NSE:SAIL"},
    "RECLTD":           {"yf": "RECLTD.NS",       "nse": "RECLTD",      "tv": "NSE:RECLTD"},
    "PFC":              {"yf": "PFC.NS",          "nse": "PFC",         "tv": "NSE:PFC"},
    "HAL":              {"yf": "HAL.NS",          "nse": "HAL",         "tv": "NSE:HAL"},
    "BEL":              {"yf": "BEL.NS",          "nse": "BEL",         "tv": "NSE:BEL"},
    "LICHSGFIN":        {"yf": "LICHSGFIN.NS",    "nse": "LICHSGFIN",   "tv": "NSE:LICHSGFIN"},
    "MOTHERSON":        {"yf": "MOTHERSON.NS",    "nse": "MOTHERSON",   "tv": "NSE:MOTHERSON"},
    "MANAPPURAM":       {"yf": "MANAPPURAM.NS",   "nse": "MANAPPURAM",  "tv": "NSE:MANAPPURAM"},
    "MUTHOOTFIN":       {"yf": "MUTHOOTFIN.NS",   "nse": "MUTHOOTFIN",  "tv": "NSE:MUTHOOTFIN"},
    # ── Banking & Finance (extended) ──
    "FEDERALBNK":       {"yf": "FEDERALBNK.NS",   "nse": "FEDERALBNK",  "tv": "NSE:FEDERALBNK"},
    "BANDHANBNK":       {"yf": "BANDHANBNK.NS",   "nse": "BANDHANBNK",  "tv": "NSE:BANDHANBNK"},
    "CANBK":            {"yf": "CANBK.NS",        "nse": "CANBK",       "tv": "NSE:CANBK"},
    "UNIONBANK":        {"yf": "UNIONBANK.NS",    "nse": "UNIONBANK",   "tv": "NSE:UNIONBANK"},
    "RBLBANK":          {"yf": "RBLBANK.NS",      "nse": "RBLBANK",     "tv": "NSE:RBLBANK"},
    "CHOLAFIN":         {"yf": "CHOLAFIN.NS",     "nse": "CHOLAFIN",    "tv": "NSE:CHOLAFIN"},
    "ABCAPITAL":        {"yf": "ABCAPITAL.NS",    "nse": "ABCAPITAL",   "tv": "NSE:ABCAPITAL"},
    "ICICIPRULI":       {"yf": "ICICIPRULI.NS",   "nse": "ICICIPRULI",  "tv": "NSE:ICICIPRULI"},
    "ICICIGI":          {"yf": "ICICIGI.NS",      "nse": "ICICIGI",     "tv": "NSE:ICICIGI"},
    "MFSL":             {"yf": "MFSL.NS",         "nse": "MFSL",        "tv": "NSE:MFSL"},
    "CANFINHOME":       {"yf": "CANFINHOME.NS",   "nse": "CANFINHOME",  "tv": "NSE:CANFINHOME"},
    "PNBHOUSING":       {"yf": "PNBHOUSING.NS",   "nse": "PNBHOUSING",  "tv": "NSE:PNBHOUSING"},
    "IIFL":             {"yf": "IIFL.NS",         "nse": "IIFL",        "tv": "NSE:IIFL"},
    "UGROCAP":          {"yf": "UGROCAP.NS",      "nse": "UGROCAP",     "tv": "NSE:UGROCAP"},
    # ── IT / Technology ──
    "MPHASIS":          {"yf": "MPHASIS.NS",      "nse": "MPHASIS",     "tv": "NSE:MPHASIS"},
    "COFORGE":          {"yf": "COFORGE.NS",      "nse": "COFORGE",     "tv": "NSE:COFORGE"},
    "PERSISTENT":       {"yf": "PERSISTENT.NS",   "nse": "PERSISTENT",  "tv": "NSE:PERSISTENT"},
    "LTTS":             {"yf": "LTTS.NS",         "nse": "LTTS",        "tv": "NSE:LTTS"},
    "OFSS":             {"yf": "OFSS.NS",         "nse": "OFSS",        "tv": "NSE:OFSS"},
    "KPITTECH":         {"yf": "KPITTECH.NS",     "nse": "KPITTECH",    "tv": "NSE:KPITTECH"},
    "TATAELXSI":        {"yf": "TATAELXSI.NS",    "nse": "TATAELXSI",   "tv": "NSE:TATAELXSI"},
    "MASTEK":           {"yf": "MASTEK.NS",       "nse": "MASTEK",      "tv": "NSE:MASTEK"},
    # ── Auto & Auto Ancillaries ──
    "ASHOKLEY":         {"yf": "ASHOKLEY.NS",     "nse": "ASHOKLEY",    "tv": "NSE:ASHOKLEY"},
    "BALKRISIND":       {"yf": "BALKRISIND.NS",   "nse": "BALKRISIND",  "tv": "NSE:BALKRISIND"},
    "BOSCHLTD":         {"yf": "BOSCHLTD.NS",     "nse": "BOSCHLTD",    "tv": "NSE:BOSCHLTD"},
    "APOLLOTYRE":       {"yf": "APOLLOTYRE.NS",   "nse": "APOLLOTYRE",  "tv": "NSE:APOLLOTYRE"},
    "MRF":              {"yf": "MRF.NS",          "nse": "MRF",         "tv": "NSE:MRF"},
    "ESCORTS":          {"yf": "ESCORTS.NS",      "nse": "ESCORTS",     "tv": "NSE:ESCORTS"},
    "TIINDIA":          {"yf": "TIINDIA.NS",      "nse": "TIINDIA",     "tv": "NSE:TIINDIA"},
    "ENDURANCE":        {"yf": "ENDURANCE.NS",    "nse": "ENDURANCE",   "tv": "NSE:ENDURANCE"},
    # ── Pharma & Healthcare ──
    "BIOCON":           {"yf": "BIOCON.NS",       "nse": "BIOCON",      "tv": "NSE:BIOCON"},
    "LUPIN":            {"yf": "LUPIN.NS",        "nse": "LUPIN",       "tv": "NSE:LUPIN"},
    "AUROPHARMA":       {"yf": "AUROPHARMA.NS",   "nse": "AUROPHARMA",  "tv": "NSE:AUROPHARMA"},
    "GRANULES":         {"yf": "GRANULES.NS",     "nse": "GRANULES",    "tv": "NSE:GRANULES"},
    "ALKEM":            {"yf": "ALKEM.NS",        "nse": "ALKEM",       "tv": "NSE:ALKEM"},
    "GLAND":            {"yf": "GLAND.NS",        "nse": "GLAND",       "tv": "NSE:GLAND"},
    "LALPATHLAB":       {"yf": "LALPATHLAB.NS",   "nse": "LALPATHLAB",  "tv": "NSE:LALPATHLAB"},
    "IPCALAB":          {"yf": "IPCALAB.NS",      "nse": "IPCALAB",     "tv": "NSE:IPCALAB"},
    "TORNTPHARM":       {"yf": "TORNTPHARM.NS",   "nse": "TORNTPHARM",  "tv": "NSE:TORNTPHARM"},
    "ABBOTINDIA":       {"yf": "ABBOTINDIA.NS",   "nse": "ABBOTINDIA",  "tv": "NSE:ABBOTINDIA"},
    "METROPOLIS":       {"yf": "METROPOLIS.NS",   "nse": "METROPOLIS",  "tv": "NSE:METROPOLIS"},
    "GLENMARK":         {"yf": "GLENMARK.NS",     "nse": "GLENMARK",    "tv": "NSE:GLENMARK"},
    # ── FMCG / Consumer ──
    "HINDUNILVR":       {"yf": "HINDUNILVR.NS",   "nse": "HINDUNILVR",  "tv": "NSE:HINDUNILVR"},
    "DABUR":            {"yf": "DABUR.NS",        "nse": "DABUR",       "tv": "NSE:DABUR"},
    "MARICO":           {"yf": "MARICO.NS",       "nse": "MARICO",      "tv": "NSE:MARICO"},
    "GODREJCP":         {"yf": "GODREJCP.NS",     "nse": "GODREJCP",    "tv": "NSE:GODREJCP"},
    "COLPAL":           {"yf": "COLPAL.NS",       "nse": "COLPAL",      "tv": "NSE:COLPAL"},
    "EMAMILTD":         {"yf": "EMAMILTD.NS",     "nse": "EMAMILTD",    "tv": "NSE:EMAMILTD"},
    "VBL":              {"yf": "VBL.NS",          "nse": "VBL",         "tv": "NSE:VBL"},
    "JUBLFOOD":         {"yf": "JUBLFOOD.NS",     "nse": "JUBLFOOD",    "tv": "NSE:JUBLFOOD"},
    "UBL":              {"yf": "UBL.NS",          "nse": "UBL",         "tv": "NSE:UBL"},
    "MCDOWELL-N":       {"yf": "MCDOWELL-N.NS",   "nse": "MCDOWELL-N",  "tv": "NSE:MCDOWELL_N"},
    "DEVYANI":          {"yf": "DEVYANI.NS",      "nse": "DEVYANI",     "tv": "NSE:DEVYANI"},
    "SAPPHIRE":         {"yf": "SAPPHIRE.NS",     "nse": "SAPPHIRE",    "tv": "NSE:SAPPHIRE"},
    # ── Energy / Power ──
    "GAIL":             {"yf": "GAIL.NS",         "nse": "GAIL",        "tv": "NSE:GAIL"},
    "IOC":              {"yf": "IOC.NS",          "nse": "IOC",         "tv": "NSE:IOC"},
    "ADANIGREEN":       {"yf": "ADANIGREEN.NS",   "nse": "ADANIGREEN",  "tv": "NSE:ADANIGREEN"},
    "ADANIPORTS":       {"yf": "ADANIPORTS.NS",   "nse": "ADANIPORTS",  "tv": "NSE:ADANIPORTS"},
    "ADANIENT":         {"yf": "ADANIENT.NS",     "nse": "ADANIENT",    "tv": "NSE:ADANIENT"},
    "TORNTPOWER":       {"yf": "TORNTPOWER.NS",   "nse": "TORNTPOWER",  "tv": "NSE:TORNTPOWER"},
    "CESC":             {"yf": "CESC.NS",         "nse": "CESC",        "tv": "NSE:CESC"},
    "IEX":              {"yf": "IEX.NS",          "nse": "IEX",         "tv": "NSE:IEX"},
    "NHPC":             {"yf": "NHPC.NS",         "nse": "NHPC",        "tv": "NSE:NHPC"},
    "SJVN":             {"yf": "SJVN.NS",         "nse": "SJVN",        "tv": "NSE:SJVN"},
    "INOXWIND":         {"yf": "INOXWIND.NS",     "nse": "INOXWIND",    "tv": "NSE:INOXWIND"},
    # ── Metals & Mining ──
    "NATIONALUM":       {"yf": "NATIONALUM.NS",   "nse": "NATIONALUM",  "tv": "NSE:NATIONALUM"},
    "JSPL":             {"yf": "JSPL.NS",         "nse": "JSPL",        "tv": "NSE:JSPL"},
    "HINDZINC":         {"yf": "HINDZINC.NS",     "nse": "HINDZINC",    "tv": "NSE:HINDZINC"},
    "NMDC":             {"yf": "NMDC.NS",         "nse": "NMDC",        "tv": "NSE:NMDC"},
    "APLAPOLLO":        {"yf": "APLAPOLLO.NS",    "nse": "APLAPOLLO",   "tv": "NSE:APLAPOLLO"},
    "WELCORP":          {"yf": "WELCORP.NS",      "nse": "WELCORP",     "tv": "NSE:WELCORP"},
    # ── Real Estate ──
    "OBEROIREAL":       {"yf": "OBEROIREAL.NS",   "nse": "OBEROIREAL",  "tv": "NSE:OBEROIREAL"},
    "GODREJPROP":       {"yf": "GODREJPROP.NS",   "nse": "GODREJPROP",  "tv": "NSE:GODREJPROP"},
    "BRIGADE":          {"yf": "BRIGADE.NS",      "nse": "BRIGADE",     "tv": "NSE:BRIGADE"},
    "PRESTIGE":         {"yf": "PRESTIGE.NS",     "nse": "PRESTIGE",    "tv": "NSE:PRESTIGE"},
    "SOBHA":            {"yf": "SOBHA.NS",        "nse": "SOBHA",       "tv": "NSE:SOBHA"},
    "PHOENIXLTD":       {"yf": "PHOENIXLTD.NS",   "nse": "PHOENIXLTD",  "tv": "NSE:PHOENIXLTD"},
    "LODHA":            {"yf": "LODHA.NS",        "nse": "LODHA",       "tv": "NSE:LODHA"},
    # ── Cement ──
    "SHREECEM":         {"yf": "SHREECEM.NS",     "nse": "SHREECEM",    "tv": "NSE:SHREECEM"},
    "AMBUJACEM":        {"yf": "AMBUJACEM.NS",    "nse": "AMBUJACEM",   "tv": "NSE:AMBUJACEM"},
    "ACC":              {"yf": "ACC.NS",          "nse": "ACC",         "tv": "NSE:ACC"},
    "RAMCOCEM":         {"yf": "RAMCOCEM.NS",     "nse": "RAMCOCEM",    "tv": "NSE:RAMCOCEM"},
    "DALBHARAT":        {"yf": "DALBHARAT.NS",    "nse": "DALBHARAT",   "tv": "NSE:DALBHARAT"},
    "JKCEMENT":         {"yf": "JKCEMENT.NS",     "nse": "JKCEMENT",    "tv": "NSE:JKCEMENT"},
    # ── Chemicals ──
    "PIDILITIND":       {"yf": "PIDILITIND.NS",   "nse": "PIDILITIND",  "tv": "NSE:PIDILITIND"},
    "DEEPAKNITR":       {"yf": "DEEPAKNITR.NS",   "nse": "DEEPAKNITR",  "tv": "NSE:DEEPAKNITR"},
    "NAVINFLUOR":       {"yf": "NAVINFLUOR.NS",   "nse": "NAVINFLUOR",  "tv": "NSE:NAVINFLUOR"},
    "SRF":              {"yf": "SRF.NS",          "nse": "SRF",         "tv": "NSE:SRF"},
    "AARTIIND":         {"yf": "AARTIIND.NS",     "nse": "AARTIIND",    "tv": "NSE:AARTIIND"},
    "TATACHEM":         {"yf": "TATACHEM.NS",     "nse": "TATACHEM",    "tv": "NSE:TATACHEM"},
    "ASTRAL":           {"yf": "ASTRAL.NS",       "nse": "ASTRAL",      "tv": "NSE:ASTRAL"},
    "CLEAN":            {"yf": "CLEAN.NS",        "nse": "CLEAN",       "tv": "NSE:CLEAN"},
    # ── Capital Goods / Industrial ──
    "SIEMENS":          {"yf": "SIEMENS.NS",      "nse": "SIEMENS",     "tv": "NSE:SIEMENS"},
    "ABB":              {"yf": "ABB.NS",          "nse": "ABB",         "tv": "NSE:ABB"},
    "CUMMINSIND":       {"yf": "CUMMINSIND.NS",   "nse": "CUMMINSIND",  "tv": "NSE:CUMMINSIND"},
    "THERMAX":          {"yf": "THERMAX.NS",      "nse": "THERMAX",     "tv": "NSE:THERMAX"},
    "BHARATFORG":       {"yf": "BHARATFORG.NS",   "nse": "BHARATFORG",  "tv": "NSE:BHARATFORG"},
    "CGPOWER":          {"yf": "CGPOWER.NS",      "nse": "CGPOWER",     "tv": "NSE:CGPOWER"},
    "TITAGARH":         {"yf": "TITAGARH.NS",     "nse": "TITAGARH",    "tv": "NSE:TITAGARH"},
    "RAILTEL":          {"yf": "RAILTEL.NS",      "nse": "RAILTEL",     "tv": "NSE:RAILTEL"},
    # ── Consumer Durables / Retail ──
    "HAVELLS":          {"yf": "HAVELLS.NS",      "nse": "HAVELLS",     "tv": "NSE:HAVELLS"},
    "VOLTAS":           {"yf": "VOLTAS.NS",       "nse": "VOLTAS",      "tv": "NSE:VOLTAS"},
    "CROMPTON":         {"yf": "CROMPTON.NS",     "nse": "CROMPTON",    "tv": "NSE:CROMPTON"},
    "POLYCAB":          {"yf": "POLYCAB.NS",      "nse": "POLYCAB",     "tv": "NSE:POLYCAB"},
    "BATAINDIA":        {"yf": "BATAINDIA.NS",    "nse": "BATAINDIA",   "tv": "NSE:BATAINDIA"},
    "PAGEIND":          {"yf": "PAGEIND.NS",      "nse": "PAGEIND",     "tv": "NSE:PAGEIND"},
    "VEDANT":           {"yf": "MANYAVAR.NS",     "nse": "MANYAVAR",    "tv": "NSE:MANYAVAR"},
    "BERGEPAINT":       {"yf": "BERGEPAINT.NS",   "nse": "BERGEPAINT",  "tv": "NSE:BERGEPAINT"},
    "KANSAINER":        {"yf": "KANSAINER.NS",    "nse": "KANSAINER",   "tv": "NSE:KANSAINER"},
    # ── New-age / Digital / E-Commerce ──
    "AVENUE":           {"yf": "AVENUE.NS",       "nse": "AVENUE",      "tv": "NSE:AVENUE"},
    "NYKAA":            {"yf": "NYKAA.NS",        "nse": "NYKAA",       "tv": "NSE:NYKAA"},
    "PAYTM":            {"yf": "PAYTM.NS",        "nse": "PAYTM",       "tv": "NSE:PAYTM"},
    "POLICYBZR":        {"yf": "POLICYBZR.NS",    "nse": "POLICYBZR",   "tv": "NSE:POLICYBZR"},
    "NAUKRI":           {"yf": "NAUKRI.NS",       "nse": "NAUKRI",      "tv": "NSE:NAUKRI"},
    "INDIAMART":        {"yf": "INDIAMART.NS",    "nse": "INDIAMART",   "tv": "NSE:INDIAMART"},
    "SWIGGY":           {"yf": "SWIGGY.NS",       "nse": "SWIGGY",      "tv": "NSE:SWIGGY"},
    "CARTRADE":         {"yf": "CARTRADE.NS",     "nse": "CARTRADE",    "tv": "NSE:CARTRADE"},
    # ── PSU / Infrastructure ──
    "IRFC":             {"yf": "IRFC.NS",         "nse": "IRFC",        "tv": "NSE:IRFC"},
    "CONCOR":           {"yf": "CONCOR.NS",       "nse": "CONCOR",      "tv": "NSE:CONCOR"},
    "RVNL":             {"yf": "RVNL.NS",         "nse": "RVNL",        "tv": "NSE:RVNL"},
    "HUDCO":            {"yf": "HUDCO.NS",        "nse": "HUDCO",       "tv": "NSE:HUDCO"},
    "IREDA":            {"yf": "IREDA.NS",        "nse": "IREDA",       "tv": "NSE:IREDA"},
    # ── Media / Hospitality / Others ──
    "INDHOTEL":         {"yf": "INDHOTEL.NS",     "nse": "INDHOTEL",    "tv": "NSE:INDHOTEL"},
    "PVRINOX":          {"yf": "PVRINOX.NS",      "nse": "PVRINOX",     "tv": "NSE:PVRINOX"},
    "ZEEL":             {"yf": "ZEEL.NS",         "nse": "ZEEL",        "tv": "NSE:ZEEL"},
    "JUSTDIAL":         {"yf": "JUSTDIAL.NS",     "nse": "JUSTDIAL",    "tv": "NSE:JUSTDIAL"},
    "HFCL":             {"yf": "HFCL.NS",         "nse": "HFCL",        "tv": "NSE:HFCL"},
    "NAZARA":           {"yf": "NAZARA.NS",       "nse": "NAZARA",      "tv": "NSE:NAZARA"},
}

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

REFRESH_INTERVAL_SECONDS = 150

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

STOP_LOSS_PCT = 0.3
TARGET_PCT = 1.0

MIN_INDICATORS_FOR_SIGNAL = 3

MONEYCONTROL_URL = "https://www.moneycontrol.com/news/business/markets/"
NEWS_COUNT = 5

# Email Alert Settings (Gmail SMTP)
# To set up: Go to Google Account → Security → 2-Step Verification → App Passwords
# Generate a 16-char app password and put it below
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")        # your Gmail address
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")     # Gmail App Password (16 chars)
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")     # client's email to receive alerts

# Fast2SMS Settings
FAST2SMS_API_KEY = os.environ.get("FAST2SMS_API_KEY", "")  # https://www.fast2sms.com

# Supabase Settings (persistent storage for subscribers + SMS log)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
