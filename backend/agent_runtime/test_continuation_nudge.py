"""Tests for CONTINUATION_RE / PLANNING_RE nudge logic."""

import pytest
from backend.agent_runtime.llm_response_parser import CONTINUATION_RE, PLANNING_RE


def _would_nudge(text: str) -> bool:
    """Return True if the nudge system would fire on *text*."""
    return bool(CONTINUATION_RE.search(text)) and not bool(PLANNING_RE.search(text))


# ── Cases that SHOULD be nudged (genuine continuation promises) ────────────

@pytest.mark.parametrize("text", [
    "Saya akan melanjutkan mengecek file tersebut.",
    "Baik, saya akan mulai mengerjakan task ini.",
    "Let me continue working on the implementation.",
    "I'll now proceed to update the config.",
    "Sekarang saya akan coba jalankan testnya.",
    "Saya akan lakukan langkah berikutnya.",
    "Mari kita lanjutkan ke bagian selanjutnya.",
    "Tunggu sebentar, sedang memproses.",
    "Oke, saya kerjakan sekarang.",
    "Saya perlu mengecek dulu.",
])
def test_nudge_fires_on_continuation(text):
    assert _would_nudge(text), f"Expected nudge for: {text!r}"


# ── Cases that should NOT be nudged (false positives) ──────────────────────

@pytest.mark.parametrize("text", [
    # The original false positive from session 25ac767d
    (
        "Jadwal sudah dibuat. **Ringkasan:**\n\n"
        "- **Nama:** Cek total tasks\n"
        "- **Aksi:** Saya akan mengecek semua task di kolom TODO"
    ),
    # Completion with 'sudah selesai'
    "Task sudah selesai. Saya akan mengirimkan laporannya nanti.",
    # Completion with 'sudah berhasil'
    "Deployment sudah berhasil. Saya akan monitor hasilnya.",
    # Completion with 'sudah dijadwalkan'
    "Reminder sudah dijadwalkan. Saya akan kirimkan pukul 10.",
    # Completion with 'sudah dikirim'
    "Pesan sudah dikirim. Saya akan follow up nanti.",
    # Summary keyword
    "Berikut ringkasan dari task yang saya kerjakan hari ini.",
    # Planning patterns (pre-existing)
    "Berikut adalah rencana yang saya buat.",
    "Apakah Anda setuju dengan plan ini?",
])
def test_nudge_suppressed_on_completion(text):
    assert not _would_nudge(text), f"Should NOT nudge for: {text!r}"


# ── Edge cases ─────────────────────────────────────────────────────────────

def test_no_continuation_phrase_no_nudge():
    """Plain informational text should never be nudged."""
    assert not _would_nudge("Berikut hasilnya: ada 5 task di kolom TODO.")


def test_planning_re_does_not_negate_without_completion():
    """PLANNING_RE should not fire on text without plan/completion markers."""
    text = "Saya akan mengecek semua task sekarang."
    assert CONTINUATION_RE.search(text)
    assert not PLANNING_RE.search(text)
