from datetime import datetime
from getpass import getpass
from pathlib import Path
import pandas as pd
from sqlalchemy import URL, Date, create_engine, text

# LANGKAH 0: Menyiapkan alat dan alamat berkas
FOLDER_REPO = Path(__file__).resolve().parent.parent
BERKAS_MENTAH = FOLDER_REPO / "data" / "daftar_arsip_fakultas.csv"
FOLDER_OUTPUT = FOLDER_REPO / "output"
FOLDER_OUTPUT.mkdir(exist_ok=True)
TANGGAL_ACUAN = pd.Timestamp("2026-12-31")

# LANGKAH 1: Membaca CSV
df = pd.read_csv(BERKAS_MENTAH, dtype=str, keep_default_na=False)
print("=== LANGKAH 1 Kenali data ===")
print("Jumlah baris, kolom :", df.shape)
print("Nama kolom :", list(df.columns))
print(df.head())

# LANGKAH 2: Merapikan teks
for kolom in df.columns:
    df[kolom] = df[kolom].str.strip()
df["judul"] = df["judul"].str.replace(r"\s+", " ", regex=True)

# LANGKAH 3: Kosakata terkendali
KAMUS_UNIT = {
    "kepegawaian": "Kepegawaian", "kpg": "Kepegawaian", "kepeg.": "Kepegawaian",
    "keuangan": "Keuangan", "keu": "Keuangan", "keu.": "Keuangan",
    "akademik": "Akademik", "akd": "Akademik", "akad.": "Akademik",
    "kemahasiswaan": "Kemahasiswaan", "kmh": "Kemahasiswaan",
    "umum dan perlengkapan": "Umum dan Perlengkapan",
    "umum & perlengkapan": "Umum dan Perlengkapan",
    "ump": "Umum dan Perlengkapan",
}

KAMUS_MEDIA = {
    "kertas": "Kertas", "fisik": "Kertas",
    "elektronik": "Elektronik", "digital": "Elektronik", "e-arsip": "Elektronik",
}

KAMUS_AKSES = {
    "biasa": "Biasa", "terbatas": "Terbatas", "rahasia": "Rahasia"
}

df["unit_pencipta"] = df["unit_pencipta"].str.lower().map(KAMUS_UNIT)
df["media"] = df["media"].str.lower().map(KAMUS_MEDIA)
df["tingkat_akses"] = df["tingkat_akses"].str.lower().map(KAMUS_AKSES)

print("\n=== LANGKAH 3 Nilai unit setelah dibakukan ===")
print(df["unit_pencipta"].value_counts(dropna=False))

# LANGKAH 4: Menyeragamkan tanggal ke ISO 8601
def baca_tanggal(teks):
    for pola in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return pd.Timestamp(datetime.strptime(teks, pola))
        except ValueError:
            pass
    return pd.NaT

df["tanggal_arsip"] = df["tanggal_arsip"].apply(baca_tanggal)
df["tahun"] = df["tanggal_arsip"].dt.year.astype("Int64")
df["jumlah_lembar"] = pd.to_numeric(df["jumlah_lembar"], errors="coerce").astype("Int64")

# LANGKAH 5: Membuang baris duplikat
jumlah_awal = len(df)
df = df.drop_duplicates()
print("\n=== LANGKAH 5 Duplikat ===")
print("Duplikat dibuang :", jumlah_awal - len(df))
print("Sisa baris :", len(df))

# LANGKAH 6: Menghubungkan dengan Jadwal Retensi Arsip (JRA)
JRA = pd.DataFrame([
    ("KP.01", "Formasi Pegawai", 2, 3, "Musnah"),
    ("KP.02", "Cuti Pegawai", 1, 2, "Musnah"),
    ("KP.03", "Penilaian Kinerja", 2, 3, "Musnah"),
    ("KP.04", "Pengangkatan Pegawai", 2, 8, "Permanen"),
    ("KU.01", "Pertanggungjawaban Keuangan", 2, 8, "Musnah"),
    ("KU.02", "Laporan Keuangan Tahunan", 2, 8, "Permanen"),
    ("AK.01", "Jadwal Perkuliahan", 1, 1, "Musnah"),
    ("AK.02", "Daftar Nilai", 2, 5, "Musnah"),
    ("AK.03", "Kurikulum dan RPS", 3, 5, "Permanen"),
    ("KM.01", "Beasiswa", 2, 3, "Musnah"),
    ("KM.02", "Kegiatan Kemahasiswaan", 2, 3, "Musnah"),
    ("UM.01", "Pengadaan Barang", 2, 5, "Musnah"),
    ("UM.02", "Surat Edaran Pimpinan", 2, 3, "Permanen"),
], columns=["kode_klasifikasi", "nama_klasifikasi", "retensi_aktif", "retensi_inaktif", "keterangan_jra"])

df = df.merge(JRA, on="kode_klasifikasi", how="left")
for kolom in ["retensi_aktif", "retensi_inaktif"]:
    df[kolom] = df[kolom].astype("Int64")

# LANGKAH 7: Menghitung akhir retensi dan status arsip
def tambah_tahun(tanggal, tahun):
    if pd.isna(tanggal) or pd.isna(tahun):
        return pd.NaT
    return tanggal + pd.DateOffset(years=int(tahun))

df["akhir_aktif"] = [tambah_tahun(t, n) for t, n in zip(df["tanggal_arsip"], df["retensi_aktif"])]
df["akhir_inaktif"] = [tambah_tahun(t, n) for t, n in zip(df["akhir_aktif"], df["retensi_inaktif"])]

def tentukan_status(baris):
    if pd.isna(baris["akhir_inaktif"]):
        return "Perlu Dicek"
    if TANGGAL_ACUAN < baris["akhir_aktif"]:
        return "Aktif"
    if TANGGAL_ACUAN < baris["akhir_inaktif"]:
        return "Inaktif"
    if baris["keterangan_jra"] == "Musnah":
        return "Usul Musnah"
    return "Serah ke Arsip Statis"

df["status_retensi"] = df.apply(tentukan_status, axis=1)

# LANGKAH 8: Menandai masalah kualitas metadata
def catatan_kualitas(baris):
    masalah = []
    if baris["judul"] == "":
        masalah.append("judul kosong")
    if pd.isna(baris["tanggal_arsip"]):
        masalah.append("tanggal kosong")
    if pd.isna(baris["nama_klasifikasi"]):
        masalah.append("kode tidak ada di JRA")
    return "; ".join(masalah)

df["catatan_kualitas"] = df.apply(catatan_kualitas, axis=1)
df["perlu_dicek"] = df["catatan_kualitas"] != ""

# LANGKAH 9: Ringkasan di layar
print("\n=== LANGKAH 9 Ringkasan ===")
print("Total arsip bersih :", len(df))
print("\nJumlah per status retensi:")
print(df["status_retensi"].value_counts())
print("\nPerlu dicek manual :", df["perlu_dicek"].sum(), "arsip")

# LANGKAH 10: Merapikan urutan kolom dan menyimpan salinan CSV
URUTAN = [
    "no_arsip", "kode_klasifikasi", "nama_klasifikasi", "judul",
    "unit_pencipta", "tanggal_arsip", "tahun", "media",
    "jumlah_lembar", "tingkat_akses", "lokasi_simpan",
    "retensi_aktif", "retensi_inaktif", "keterangan_jra",
    "akhir_aktif", "akhir_inaktif", "status_retensi",
    "perlu_dicek", "catatan_kualitas"
]
df = df[URUTAN].sort_values("no_arsip")
df.to_csv(FOLDER_OUTPUT / "daftar_arsip_bersih.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
print("\nSalinan CSV tersimpan:", FOLDER_OUTPUT)

# LANGKAH 11: Menyimpan ke database PostgreSQL
PG_HOST = "localhost"
PG_PORT = 5432
PG_USER = "postgres"
PG_DB = "postgres"
SKEMA = "sesi12"

PG_PASSWORD = getpass("Password PostgreSQL: ")
alamat = URL.create(
    "postgresql+psycopg2",
    username=PG_USER,
    password=PG_PASSWORD,
    host=PG_HOST,
    port=PG_PORT,
    database=PG_DB
)
mesin = create_engine(alamat)

with mesin.begin() as koneksi:
    koneksi.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SKEMA}"))
    df.to_sql(
        "arsip", koneksi, schema=SKEMA, if_exists="replace", index=False,
        dtype={"tanggal_arsip": Date(), "akhir_aktif": Date(), "akhir_inaktif": Date()}
    )
    JRA.to_sql("jra", koneksi, schema=SKEMA, if_exists="replace", index=False)
    n = koneksi.execute(text(f"SELECT COUNT(*) FROM {SKEMA}.arsip"))
    print("Tersimpan di PostgreSQL:", f"{PG_DB} > {SKEMA}.arsip", "=", n.scalar(), "baris")

print("\nSelesai!")