# Tim Agen AI — CuanBot v4

Rangkaian agen AI end-to-end untuk pengembangan CuanBot v4. Setiap agen
didefinisikan sebagai **role + prompt template** yang dijalankan manual/dialectic
di chat. Runtime proyek: **Termux Android** (GitHub sebagai source repo).

## Daftar Agen

| # | Agen | Fokus | Playbook |
|---|------|-------|----------|
| 1 | Interaction & CLI Developer | CLI + Telegram bot UI | [interaction.md](interaction.md) |
| 2 | Backend Developer | Core engine + Termux ops | [backend.md](backend.md) |
| 3 | QA Specialist | Testing & stabilitas | [qa.md](qa.md) |
| 4 | System Analyst & Business Process | Kebutuhan bisnis & alur | [system-analyst.md](system-analyst.md) |
| 5 | Security & Pentest | Secret, pentest, dependensi | [security.md](security.md) |
| 6 | Data & Quant | Backtest & optimasi strategi | [quant.md](quant.md) |
| 7 | Tech Writer | Dokumentasi sync | [tech-writer.md](tech-writer.md) |
| 8 | Code Review Specialist | Clean code & standar kualitas | [code-review.md](code-review.md) |

## Menjalankan Semua Agen Sekaligus

Untuk tugas end-to-end yang menyentuh banyak agen, pakai **master orchestrator**:
[orchestrator.md](orchestrator.md) — satu prompt yang menjalankan semua agen
berurutan dengan checkpoint semi-otonom.

## Alur Kolaborasi

```
[Perencanaan]
  System Analyst → kebutuhan + acceptance criteria
        ↓
[Desain]
  System Analyst + Backend + Quant → pendekatan
        ↓
[Implementasi]
  Backend + Interaction Developer → build
        ↓ (artifact: code diff + changelog draft)
[Review Paralel]
  ┌─ Code Review → kualitas, clean code, performa
  └─ Security → secret, logic pentest, dependency
        ↓ (artifact: review comments + approval)
[Validasi Strategi]
  Quant → backtest (jika parameter berubah)
        ↓
[Pengujian]
  QA → unit/integration/regression + stabilitas Termux
        ↓
[Dokumentasi]
  Tech Writer → README/runbook/changelog
        ↓
[Rilis]
  System Analyst → verifikasi acceptance criteria → merge → push GitHub
        ↓
[Deploy]
  Termux → git pull → restart bot
```

## Matriks RACI (Pemilik Area)

| Area | Pemilik (R) | Konsultan (C) |
|------|-------------|----------------|
| Logika trading & engine | Backend | Quant |
| Parameter strategi & threshold | Quant | System Analyst |
| CLI & Telegram bot UI | Interaction (Agen 1) | Backend |
| Manajemen secret & keamanan | Security | Backend |
| State persistence & Termux ops | Backend | Security, QA |
| Test suite & stabilitas | QA | Backend, Security |
| Kebutuhan bisnis & SLA | System Analyst | Quant |
| Dokumentasi | Tech Writer | semua agen |
| Kualitas & standar kode | Code Review | Backend |
| Linting & formatting | Code Review | Backend |

## Cara Pakai Playbook

1. Buka playbook agen yang relevan (lihat tabel di atas).
2. Salin bagian **"Prompt Template Siap Pakai"**.
3. Isi bagian `[deskripsikan tugas]` dengan konteks spesifik.
4. Jalankan di chat sebagai peran agen tersebut.
5. Patuhi **batasan tanggung jawab** — jangan melanggar domain agen lain.

## Catatan Arsitektur

- **Runtime**: Termux Android (satu-satunya). GitHub Actions BUKAN runtime.
- **Source repo**: GitHub (push dari dev PC, pull di Termux).
- **Secret**: disimpan di device Termux (file `.env`), bukan GitHub Secrets.
- **Bahasa**: Python. CLI-first. Telegram sebagai notifikasi interaktif.
