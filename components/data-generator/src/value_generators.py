"""
value_generators.py — Implement all generator types for scenario-driven data generation.

Each public generator function has the signature:
    generate_<type>(config: dict, row: dict) -> value

The dispatch entry point is:
    generate_value(col_def: dict, row: dict) -> value

Columns are assumed to be generated in schema order; derived_from and computed
columns must appear after their source columns.
"""

import math
import random
import re
import uuid as _uuid_mod
import datetime


# ---------------------------------------------------------------------------
# Lazy Faker instance (only imported if fake generator is used)
# ---------------------------------------------------------------------------

_faker_instance = None


def _get_faker():
    global _faker_instance
    if _faker_instance is None:
        try:
            from faker import Faker
            _faker_instance = Faker()
        except ImportError:
            raise RuntimeError(
                "The 'faker' package is required for the 'fake' generator type. "
                "Install it with: pip install faker"
            )
    return _faker_instance


# ---------------------------------------------------------------------------
# Individual generator functions
# ---------------------------------------------------------------------------

def _gen_uuid(config, row):
    """Random UUID v4 string."""
    return str(_uuid_mod.uuid4())


def _gen_now_jitter(config, row):
    """Current UTC time with a random 0–2 second jitter."""
    jitter = random.uniform(0, 2)
    return datetime.datetime.utcnow() + datetime.timedelta(seconds=jitter)


def _gen_range(config, row):
    """
    Uniform random int/float between min and max.
    Optional distribution: 'exponential' with lambda param (values are clamped to [min, max]).
    """
    lo = config.get("min", 0)
    hi = config.get("max", 1)
    distribution = config.get("distribution")

    if distribution == "exponential":
        lam = config.get("lambda", 1.0)
        # exponential variate, then map linearly into [lo, hi]
        val = random.expovariate(lam)
        # normalise to [0, 1] using CDF approximation (cap at 99th pct)
        cdf_99 = -math.log(0.01) / lam
        val = min(val, cdf_99) / cdf_99  # [0, 1]
        raw = lo + val * (hi - lo)
    else:
        if isinstance(lo, float) or isinstance(hi, float):
            raw = random.uniform(lo, hi)
        else:
            raw = random.randint(lo, hi)

    # Honour precision if specified
    precision = config.get("precision")
    if precision is not None:
        return round(float(raw), precision)

    # Return int if both bounds are int and no distribution forcing float
    if isinstance(lo, int) and isinstance(hi, int) and distribution is None:
        return int(raw)
    return raw


def _gen_enum(config, row):
    """Uniform random pick from a list of values."""
    values = config.get("values", [])
    if not values:
        return None
    return random.choice(values)


def _gen_weighted_enum(config, row):
    """Weighted random pick. 'values' is a dict mapping value -> weight."""
    values_map = config.get("values", {})
    if not values_map:
        return None
    keys = list(values_map.keys())
    weights = [values_map[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


def _gen_fake(config, row):
    """Call a Faker method by name. E.g. {type: fake, method: name}."""
    faker = _get_faker()
    method = config.get("method", "word")
    fn = getattr(faker, method, None)
    if fn is None:
        raise ValueError(f"Faker has no method '{method}'")
    return fn()


def _gen_pattern(config, row):
    """
    String template with placeholders:
      {seq:04d}   — zero-padded random int from seq_range
      {<col>}     — value of another column in the current row
    """
    template = config.get("template", "")
    seq_range = config.get("seq_range", [1, 9999])
    seq_val = random.randint(seq_range[0], seq_range[1])

    # Build substitution dict from current row + seq
    subs = dict(row)
    subs["seq"] = seq_val

    # Replace {key:fmt} and {key} patterns
    def replacer(m):
        key = m.group(1)
        fmt_spec = m.group(2)  # may be None
        val = subs.get(key, "")
        if fmt_spec:
            return format(val, fmt_spec)
        return str(val)

    result = re.sub(r'\{(\w+)(?::([^}]+))?\}', replacer, template)
    return result


def _gen_gaussian(config, row):
    """Normal distribution with optional min/max clamp and precision."""
    mean = config.get("mean", 0.0)
    stddev = config.get("stddev", 1.0)
    val = random.gauss(mean, stddev)

    lo = config.get("min")
    hi = config.get("max")
    if lo is not None:
        val = max(val, lo)
    if hi is not None:
        val = min(val, hi)

    precision = config.get("precision")
    if precision is not None:
        return round(val, precision)
    return val


def _gen_gaussian_per_group(config, row):
    """
    Different gaussian parameters per value of a group column.
    Falls back to overall mean/stddev if the group value isn't in profiles.
    """
    group_column = config.get("group_column", "")
    profiles = config.get("profiles", {})
    group_val = row.get(group_column)

    profile = profiles.get(group_val, {})
    mean = profile.get("mean", config.get("mean", 0.0))
    stddev = profile.get("stddev", config.get("stddev", 1.0))

    sub_config = dict(config)
    sub_config["mean"] = mean
    sub_config["stddev"] = stddev
    return _gen_gaussian(sub_config, row)


def _gen_lognormal(config, row):
    """Log-normal distribution with optional min/max clamp and precision."""
    mean = config.get("mean", 0.0)
    sigma = config.get("sigma", 1.0)
    val = random.lognormvariate(mean, sigma)

    lo = config.get("min")
    hi = config.get("max")
    if lo is not None:
        val = max(val, lo)
    if hi is not None:
        val = min(val, hi)

    precision = config.get("precision")
    if precision is not None:
        return round(val, precision)
    return val


def _gen_beta(config, row):
    """Beta distribution with alpha/beta params and optional precision."""
    alpha = config.get("alpha", 1.0)
    beta = config.get("beta", 1.0)
    val = random.betavariate(alpha, beta)

    precision = config.get("precision")
    if precision is not None:
        return round(val, precision)
    return val


def _gen_derived_from(config, row):
    """
    Look up the value of another column via a static mapping dict.
    Falls back to None if not found.
    """
    source_col = config.get("source_column", "")
    mapping = config.get("mapping", {})
    source_val = row.get(source_col)
    return mapping.get(source_val)


def _gen_computed(config, row):
    """
    Evaluate a simple Python expression referencing other columns in the row.
    Handles arithmetic (e.g. 'quantity * unit_price') and conditional
    expressions (e.g. "'blocked' if risk_score > 0.85 else 'cleared'").

    Uses eval() with a restricted namespace containing only the row's values
    and safe builtins. No SQL CASE syntax — the YAML should use Python ternary.
    """
    expression = config.get("expression", "").strip()
    if not expression:
        return None

    safe_builtins = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
    }
    namespace = {"__builtins__": safe_builtins}
    namespace.update(row)

    try:
        return eval(expression, namespace)  # noqa: S307
    except Exception as exc:
        raise ValueError(
            f"computed expression '{expression}' failed: {exc}. "
            f"Row context keys: {list(row.keys())}"
        ) from exc


def _gen_weighted_bool(config, row):
    """Boolean with configurable true_probability (default 0.5)."""
    prob = config.get("true_probability", 0.5)
    return random.random() < prob


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_GENERATORS = {
    "uuid": _gen_uuid,
    "now_jitter": _gen_now_jitter,
    "range": _gen_range,
    "enum": _gen_enum,
    "weighted_enum": _gen_weighted_enum,
    "fake": _gen_fake,
    "pattern": _gen_pattern,
    "gaussian": _gen_gaussian,
    "gaussian_per_group": _gen_gaussian_per_group,
    "lognormal": _gen_lognormal,
    "beta": _gen_beta,
    "derived_from": _gen_derived_from,
    "computed": _gen_computed,
    "weighted_bool": _gen_weighted_bool,
}


def generate_value(col_def: dict, row: dict):
    """
    Generate a single value for col_def using the current partial row dict.

    col_def format:
      {name: "...", type: "...", generator: <str|dict>}

    The generator field is either:
      - A bare string shorthand: "uuid", "now_jitter"
      - A dict with at least a 'type' key
    """
    gen_cfg = col_def.get("generator")

    if isinstance(gen_cfg, str):
        # Bare shorthand — no extra config
        gen_type = gen_cfg
        config = {}
    elif isinstance(gen_cfg, dict):
        gen_type = gen_cfg.get("type")
        config = gen_cfg
    else:
        return None

    fn = _GENERATORS.get(gen_type)
    if fn is None:
        raise ValueError(
            f"Unknown generator type '{gen_type}' for column '{col_def.get('name')}'. "
            f"Available: {sorted(_GENERATORS.keys())}"
        )

    return fn(config, row)


def generate_row(columns: list) -> dict:
    """
    Generate a complete row dict by processing columns in order.
    Each column can reference previously generated columns via derived_from/computed.
    """
    row = {}
    for col_def in columns:
        name = col_def["name"]
        row[name] = generate_value(col_def, row)
    return row


def generate_batch(columns: list, num_rows: int) -> list:
    """Generate a list of row dicts."""
    return [generate_row(columns) for _ in range(num_rows)]
