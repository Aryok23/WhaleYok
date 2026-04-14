"""
broker_profiles.py — Klasifikasi broker IDX ke kategori:
  ASING       : Broker asing / sekuritas multinasional
  INSTITUSI   : Broker lokal institusional (bank, asuransi, dana pensiun)
  RETAIL      : Broker retail / reksadana lokal kecil

Sumber referensi: IDX Member Directory + profil umum pasar IDX.
Update manual jika ada broker baru masuk/keluar.
"""

# Broker asing — biasanya smart money, sinyal kuat jika net buy
FOREIGN_BROKERS: set[str] = {
    "AK",  # UBS Securities
    "BK",  # J.P. Morgan Securities
    "CC",  # Mandiri Sekuritas (JV, treated as institutional)
    "CS",  # Credit Suisse
    "DB",  # Deutsche Securities
    "DP",  # Danareksa (JV asing)
    "FZ",  # Macquarie Capital
    "GW",  # Goldman Sachs
    "HD",  # Korea Investment & Securities
    "IJ",  # CLSA Indonesia
    "KI",  # Mirae Asset Sekuritas
    "KK",  # Phillip Securities Indonesia
    "LG",  # Citigroup Securities
    "MG",  # Morgan Stanley
    "ML",  # Merrill Lynch Indonesia
    "MQ",  # Macquarie Sekuritas
    "NI",  # BNP Paribas Securities
    "OD",  # Daiwa Capital Markets
    "RB",  # ABN AMRO (Fortis)
    "RX",  # Nomura Indonesia
    "SB",  # CIMB Sekuritas Indonesia
    "UD",  # Bahana Sekuritas (JV)
    "YP",  # Maybank Sekuritas (ex-Kim Eng)
    "YU",  # CIMB Niaga Sekuritas
    "ZP",  # Kim Eng Securities
}

# Broker institusi lokal — BUMN sekuritas, bank lokal besar
INSTITUTIONAL_BROKERS: set[str] = {
    "AF",  # Trimegah Sekuritas
    "AI",  # Bahana Sekuritas
    "AO",  # Mandiri Sekuritas
    "BW",  # BRI Danareksa Sekuritas
    "DH",  # Dinamika Usahajaya
    "DX",  # Danareksa Sekuritas
    "EP",  # MNC Sekuritas
    "GR",  # Panin Sekuritas
    "ID",  # BNI Sekuritas
    "IF",  # Samuel Sekuritas
    "KF",  # Kresna Sekuritas
    "LH",  # OCBC Sekuritas
    "OX",  # Profindo Sekuritas
    "PC",  # Reliance Sekuritas
    "PD",  # Indo Premier Sekuritas
    "RO",  # Mega Capital Sekuritas
    "RS",  # Sinarmas Sekuritas
    "SM",  # Sucor Sekuritas
    "YJ",  # Henan Putihrai
    "ZR",  # Stockbit Sekuritas
}


def classify_broker(broker_code: str) -> str:
    """Klasifikasikan kode broker ke kategori.

    Args:
        broker_code: Kode broker 2 huruf (uppercase).

    Returns:
        "ASING", "INSTITUSI", atau "RETAIL"
    """
    code = broker_code.strip().upper()
    if code in FOREIGN_BROKERS:
        return "ASING"
    if code in INSTITUTIONAL_BROKERS:
        return "INSTITUSI"
    return "RETAIL"


def is_smart_money(broker_code: str) -> bool:
    """True jika broker diklasifikasikan sebagai smart money (asing atau institusi).

    Args:
        broker_code: Kode broker 2 huruf.

    Returns:
        True jika ASING atau INSTITUSI.
    """
    return classify_broker(broker_code) in ("ASING", "INSTITUSI")
