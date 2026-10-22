"""Analysis constants. Every number that shapes a result is declared here."""

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "Spotify Extended Streaming History"
TECH_LOG_DIR = ROOT / "Spotify Technical Log Information"
WORK_DIR = ROOT / "work"
OUTPUT_DIR = ROOT / "outputs"
WEB_DATA_DIR = ROOT / "web" / "data"

@dataclass(frozen=True)
class Paths:
    """Where one run reads its export and writes its results. Defaults = this project."""
    export_dir: Path = EXPORT_DIR
    techlog_dir: Path = TECH_LOG_DIR
    work_dir: Path = WORK_DIR
    output_dir: Path = OUTPUT_DIR
    web_data_dir: Path = WEB_DATA_DIR

    @classmethod
    def under(cls, root: Path, export_dir: Path, techlog_dir: Path | None = None) -> "Paths":
        """Self-contained layout for a build: root/work, root/outputs, root/site/data."""
        root = Path(root)
        return cls(Path(export_dir), Path(techlog_dir) if techlog_dir else Path(export_dir) / "_no_techlog",
                   root / "work", root / "outputs", root / "site" / "data")


# A "play" (for play counts only) is a music record with at least 30 s played.
# Listening time never uses this threshold: it is the sum of every ms_played.
QUALIFIED_PLAY_MS = 30_000

# ts in the export is the UTC time a stream ended. Local time is inferred from
# conn_country. Countries spanning several zones get one default zone (the US
# defaults to America/New_York); override per run with `--tz US=America/Chicago`.
TZ_BY_COUNTRY = {
    "IN": "Asia/Kolkata",
    "US": "America/New_York",
    "JP": "Asia/Tokyo",
    "BT": "Asia/Thimphu",
    "AE": "Asia/Dubai",
    "QA": "Asia/Qatar",
}
FALLBACK_TZ = "UTC"

# Fields that identify the account, network or device. They are dropped right
# after timezone assignment and never reach work/, outputs/ or web/.
PRIVATE_FIELDS = (
    "username",
    "ip_addr",
    "ip_addr_decrypted",
    "user_agent_decrypted",
    "platform",
    "conn_country",
    "offline_timestamp",
)

# A track record longer than this is flagged as an implausible duration.
MAX_PLAUSIBLE_TRACK_MS = 60 * 60 * 1000

# Era detection.
LOW_ACTIVITY_MINUTES = 300  # months below this many music minutes are not segmented
PARTIAL_MONTH_MIN_COVERAGE = 0.5  # months with less day coverage are flagged partial
ERA_MIN_SIZE = 3  # minimum segment length in valid months
ERA_JUMP = 1
ERA_BETA = None  # penalty multiplier; None means "use the calibrated value" (see eras.py)

# Artist lifecycle.
ENGAGED_SHARE = 0.02  # an artist is "engaged" in a month at >= 2% of music time
ENGAGED_MIN_MINUTES = 30  # ...and at least 30 minutes
ABSENT_MAX_MINUTES = 5  # a month counts toward a gap when the artist has < 5 minutes
COMEBACK_GAP_MONTHS = 6  # a comeback needs at least 6 consecutive absent months
SUSTAINED_WINDOW = 12  # sustained: engaged in >= SUSTAINED_MIN of the 12 months
SUSTAINED_MIN = 6  # following (and including) the first engaged month
YEARLY_TOP_N = 10  # "stayed important": in the yearly top 10 by minutes

RANDOM_SEED = 20261018
