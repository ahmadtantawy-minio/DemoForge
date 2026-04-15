"""
generators.py — Scenario engine generator library for external-system.

Each generator has the signature:
    gen_<name>(params: dict, row: dict, ctx: dict) -> value

Where:
    params — params dict from the YAML schema entry
    row    — current partial row (dict of previously generated fields)
    ctx    — engine context (sequence counters, reference_data, dataset meta)

Dispatch is via generate_value(field_def, row, ctx).
"""

import datetime
import hashlib
import ipaddress
import json
import os
import random
import re
import secrets
import string
import uuid as _uuid_mod


# ---------------------------------------------------------------------------
# Lazy Faker
# ---------------------------------------------------------------------------

_faker_cache = {}


def _get_faker(locale: str = None):
    key = locale or "default"
    if key in _faker_cache:
        return _faker_cache[key]
    try:
        from faker import Faker
        inst = Faker(locale) if locale else Faker()
    except ImportError:
        raise RuntimeError("The 'faker' package is required. pip install faker")
    _faker_cache[key] = inst
    return inst


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def gen_uuid(params, row, ctx):
    return str(_uuid_mod.uuid4())


def gen_auto_increment(params, row, ctx):
    key = params.get("counter_key") or f"_seq_{id(params)}"
    counters = ctx.setdefault("_counters", {})
    if key not in counters:
        counters[key] = int(params.get("start", 1))
    val = counters[key]
    counters[key] = val + int(params.get("step", 1))
    return val


def gen_constant(params, row, ctx):
    return params.get("value")


def gen_sequence_from(params, row, ctx):
    values = params.get("values", [])
    if not values:
        return None
    key = params.get("counter_key") or f"_seqfrom_{id(params)}"
    counters = ctx.setdefault("_counters", {})
    idx = counters.get(key, 0)
    counters[key] = idx + 1
    return values[idx % len(values)]


def _parse_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.date):
        return datetime.datetime(val.year, val.month, val.day)
    if isinstance(val, str):
        try:
            return datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            pass
    return None


def gen_timestamp(params, row, ctx):
    """Params: pattern (realistic|uniform|business_hours), start, end, timezone."""
    pattern = params.get("pattern", "realistic")
    start = _parse_dt(params.get("start")) or (
        datetime.datetime.utcnow() - datetime.timedelta(days=30)
    )
    end = _parse_dt(params.get("end")) or datetime.datetime.utcnow()
    span = (end - start).total_seconds()
    if span <= 0:
        return end

    if pattern == "uniform":
        offset = random.uniform(0, span)
    elif pattern == "business_hours":
        offset = random.uniform(0, span)
        ts = start + datetime.timedelta(seconds=offset)
        # Shift to business hours 9-17 local
        hour = random.choices(
            list(range(0, 24)),
            weights=[1, 1, 1, 1, 1, 2, 3, 5, 8, 12, 14, 14, 13, 13, 12, 10, 8, 6, 4, 3, 2, 2, 1, 1],
        )[0]
        ts = ts.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))
        return ts
    else:
        # realistic: bias toward recent, diurnal variation
        # exponential decay toward end
        r = random.random() ** 2  # skew toward 0 -> closer to end
        offset = span * (1 - r)
    return start + datetime.timedelta(seconds=offset)


def gen_time_series(params, row, ctx):
    return gen_timestamp(params, row, ctx)


def gen_date(params, row, ctx):
    from_field = params.get("from_field")
    if from_field and from_field in row:
        val = row[from_field]
        if isinstance(val, datetime.datetime):
            return val.date()
        if isinstance(val, datetime.date):
            return val
        parsed = _parse_dt(val)
        if parsed:
            return parsed.date()
    start = _parse_dt(params.get("start")) or (
        datetime.datetime.utcnow() - datetime.timedelta(days=30)
    )
    end = _parse_dt(params.get("end")) or datetime.datetime.utcnow()
    span_days = max(1, (end.date() - start.date()).days)
    return start.date() + datetime.timedelta(days=random.randint(0, span_days))


def _random_ip_in_cidr(cidr: str) -> str:
    net = ipaddress.ip_network(cidr, strict=False)
    # Sample within range
    if net.num_addresses <= 2:
        return str(net.network_address)
    first = int(net.network_address) + 1
    last = int(net.broadcast_address) - 1
    return str(ipaddress.ip_address(random.randint(first, last)))


def gen_ip_address(params, row, ctx):
    ranges = params.get("ranges") or ["10.0.0.0/8"]
    known_bad_ratio = float(params.get("known_bad_ratio", 0.0))
    bad_ips = ctx.get("_known_bad_ips", [])
    if known_bad_ratio > 0 and bad_ips and random.random() < known_bad_ratio:
        return random.choice(bad_ips)
    cidr = random.choice(ranges)
    return _random_ip_in_cidr(cidr)


def gen_weighted_choice(params, row, ctx):
    choices = params.get("choices") or params.get("values") or {}
    if isinstance(choices, list):
        # list of [val, weight] or just list of values
        if choices and isinstance(choices[0], (list, tuple)):
            keys = [c[0] for c in choices]
            weights = [c[1] for c in choices]
        else:
            return random.choice(choices)
    else:
        keys = list(choices.keys())
        weights = [choices[k] for k in keys]
    if not keys:
        return None
    return random.choices(keys, weights=weights, k=1)[0]


def gen_uniform_choice(params, row, ctx):
    values = params.get("values") or params.get("choices") or []
    if not values:
        return None
    return random.choice(values)


def gen_distribution(params, row, ctx):
    dtype = params.get("type", "normal")
    lo = params.get("min")
    hi = params.get("max")
    precision = params.get("precision")

    if dtype == "normal":
        val = random.gauss(params.get("mean", 0.0), params.get("sigma", params.get("stddev", 1.0)))
    elif dtype == "lognormal":
        val = random.lognormvariate(params.get("mean", 0.0), params.get("sigma", 1.0))
    elif dtype == "uniform":
        val = random.uniform(params.get("min", 0.0), params.get("max", 1.0))
        lo = None
        hi = None
    elif dtype == "exponential":
        val = random.expovariate(params.get("lambda", 1.0))
    else:
        val = random.random()

    if lo is not None:
        val = max(val, lo)
    if hi is not None:
        val = min(val, hi)
    if precision is not None:
        return round(float(val), precision)
    return val


def gen_faker(params, row, ctx):
    method = params.get("method", "word")
    locale = params.get("locale")
    faker = _get_faker(locale)
    fn = getattr(faker, method, None)
    if fn is None:
        raise ValueError(f"Faker has no method '{method}'")
    result = fn()
    # Many faker results are fine as-is (str/int). Convert dates/datetimes.
    if isinstance(result, datetime.datetime):
        return result
    return result


def gen_ref_lookup(params, row, ctx):
    ref_id = params.get("ref")
    column = params.get("column")
    ref_data = ctx.get("_reference_data", {}).get(ref_id)
    if not ref_data:
        return None
    rows = ref_data.get("rows", [])
    cols = ref_data.get("columns", [])
    if not rows or not cols:
        return None
    col_idx = cols.index(column) if column in cols else 0

    match_field = params.get("match_field")
    match_value_from = params.get("match_value_from")
    if match_field and match_value_from:
        target = row.get(match_value_from)
        match_idx = cols.index(match_field) if match_field in cols else None
        if match_idx is not None:
            candidates = [r for r in rows if r[match_idx] == target]
            if candidates:
                return random.choice(candidates)[col_idx]

    distribution = params.get("distribution", "uniform")
    if distribution == "weighted":
        weight_col = params.get("weight_column", "weight")
        if weight_col in cols:
            w_idx = cols.index(weight_col)
            weights = [float(r[w_idx]) for r in rows]
            return random.choices(rows, weights=weights, k=1)[0][col_idx]
    return random.choice(rows)[col_idx]


def _random_domain() -> str:
    tlds = ["com", "net", "org", "info", "biz", "io", "ru", "cn", "xyz", "top"]
    label_len = random.randint(5, 12)
    label = "".join(random.choices(string.ascii_lowercase + string.digits, k=label_len))
    return f"{label}.{random.choice(tlds)}"


def _random_sha256() -> str:
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def _random_md5() -> str:
    return hashlib.md5(secrets.token_bytes(16)).hexdigest()


def _random_url() -> str:
    paths = ["admin", "login", "wp-content", "update", "api/v1", "shell", "cmd", "exec"]
    return f"http://{_random_domain()}/{random.choice(paths)}/{secrets.token_hex(4)}"


def gen_ioc(params, row, ctx):
    ioc_type = params.get("ioc_type")
    type_field = params.get("type_field")
    if type_field and type_field in row:
        ioc_type = row[type_field]
    if not ioc_type:
        ioc_type = random.choice(["ipv4", "domain", "sha256"])
    if ioc_type == "ipv4":
        return _random_ip_in_cidr(random.choice(["203.0.113.0/24", "198.51.100.0/24", "45.33.0.0/16", "185.220.0.0/16"]))
    if ioc_type == "domain":
        return _random_domain()
    if ioc_type == "sha256":
        return _random_sha256()
    if ioc_type == "md5":
        return _random_md5()
    if ioc_type == "url":
        return _random_url()
    return _random_sha256()


def gen_pattern(params, row, ctx):
    fmt = params.get("format", "")
    categories = params.get("categories")
    subs = dict(row)
    if categories:
        subs["category"] = random.choice(categories)
    subs["year"] = datetime.datetime.utcnow().year

    counter_key = params.get("counter_key") or f"_patseq_{id(params)}"
    counters = ctx.setdefault("_counters", {})
    seq_val = counters.get(counter_key, int(params.get("seq_start", 1)))
    counters[counter_key] = seq_val + 1
    subs["seq"] = seq_val

    def replacer(m):
        key = m.group(1)
        fmt_spec = m.group(2)
        val = subs.get(key, "")
        if fmt_spec:
            try:
                return format(val, fmt_spec)
            except Exception:
                return str(val)
        return str(val)

    return re.sub(r"\{(\w+)(?::([^}]+))?\}", replacer, fmt)


def gen_conditional(params, row, ctx):
    field = params.get("field")
    val = row.get(field)
    for cond in params.get("conditions", []):
        when = cond.get("when")
        matches = False
        if isinstance(when, list):
            matches = val in when
        elif isinstance(when, dict):
            # simple op map: {eq: x, gt: y, lt: y, in: [...]}
            ok = True
            if "eq" in when:
                ok = ok and (val == when["eq"])
            if "in" in when:
                ok = ok and (val in when["in"])
            if "gt" in when and val is not None:
                ok = ok and (val > when["gt"])
            if "lt" in when and val is not None:
                ok = ok and (val < when["lt"])
            matches = ok
        else:
            matches = (val == when)
        if matches:
            sub_def = {"generator": cond.get("generator"), "params": cond.get("params", {})}
            return generate_value(sub_def, row, ctx)
    default = params.get("default")
    if isinstance(default, dict) and "generator" in default:
        return generate_value(default, row, ctx)
    return default


def gen_nullable(params, row, ctx):
    null_ratio = float(params.get("null_ratio", 0.1))
    if random.random() < null_ratio:
        return None
    sub_def = {"generator": params.get("generator"), "params": params.get("params", {})}
    return generate_value(sub_def, row, ctx)


def gen_json_object(params, row, ctx):
    if params.get("type") == "array":
        items = params.get("sample_from", [])
        mn = int(params.get("min_items", 1))
        mx = int(params.get("max_items", len(items)))
        k = random.randint(mn, min(mx, len(items)))
        return json.dumps(random.sample(items, k))
    fields = params.get("fields", [])
    obj = {}
    for f in fields:
        name = f.get("name")
        obj[name] = generate_value(f, row, ctx)
    return json.dumps(obj)


_LOREM = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud "
    "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat"
).split()


def gen_text_block(params, row, ctx):
    mn = int(params.get("min_words", 5))
    mx = int(params.get("max_words", 20))
    n = random.randint(mn, mx)
    return " ".join(random.choices(_LOREM, k=n))


_REGION_BOUNDS = {
    "us": (24.0, 49.0, -125.0, -66.0),
    "eu": (36.0, 60.0, -10.0, 30.0),
    "apac": (-40.0, 50.0, 70.0, 150.0),
    "global": (-60.0, 70.0, -180.0, 180.0),
}


def gen_geo_coordinate(params, row, ctx):
    region = str(params.get("region", "global")).lower()
    bounds = _REGION_BOUNDS.get(region, _REGION_BOUNDS["global"])
    lat = round(random.uniform(bounds[0], bounds[1]), 6)
    lon = round(random.uniform(bounds[2], bounds[3]), 6)
    return {"lat": lat, "lon": lon}


def gen_mac_address(params, row, ctx):
    prefix = params.get("prefix")
    if prefix:
        parts = [prefix]
        needed = 6 - prefix.count(":") - 1
        for _ in range(needed):
            parts.append(f"{random.randint(0, 255):02x}")
    else:
        parts = [f"{random.randint(0, 255):02x}" for _ in range(6)]
    return ":".join(parts)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_GENERATORS = {
    "uuid": gen_uuid,
    "auto_increment": gen_auto_increment,
    "timestamp": gen_timestamp,
    "time_series": gen_time_series,
    "date": gen_date,
    "ip_address": gen_ip_address,
    "weighted_choice": gen_weighted_choice,
    "uniform_choice": gen_uniform_choice,
    "distribution": gen_distribution,
    "faker": gen_faker,
    "ref_lookup": gen_ref_lookup,
    "ioc": gen_ioc,
    "pattern": gen_pattern,
    "conditional": gen_conditional,
    "nullable": gen_nullable,
    "constant": gen_constant,
    "sequence_from": gen_sequence_from,
    "json_object": gen_json_object,
    "text_block": gen_text_block,
    "geo_coordinate": gen_geo_coordinate,
    "mac_address": gen_mac_address,
}


def generate_value(field_def: dict, row: dict, ctx: dict):
    """Dispatch a field definition to its generator."""
    gen = field_def.get("generator")
    params = field_def.get("params", {}) or {}

    if isinstance(gen, dict):
        gen_name = gen.get("type")
        params = {**gen, **params}
        params.pop("type", None)
    else:
        gen_name = gen

    if not gen_name:
        return None

    fn = _GENERATORS.get(gen_name)
    if fn is None:
        raise ValueError(
            f"Unknown generator '{gen_name}' for field '{field_def.get('name')}'. "
            f"Available: {sorted(_GENERATORS.keys())}"
        )
    return fn(params, row, ctx)


def generate_row(schema: list, ctx: dict) -> dict:
    row = {}
    for field in schema:
        name = field["name"]
        nullable = field.get("nullable", True)
        val = generate_value(field, row, ctx)
        if val is None and not nullable:
            # regenerate once
            val = generate_value(field, row, ctx)
        row[name] = val
    return row


def generate_batch(schema: list, count: int, ctx: dict) -> list:
    return [generate_row(schema, ctx) for _ in range(count)]
