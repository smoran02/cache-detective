"""The tests' own meter, so a bug in your meter() can't hide a bad fix."""
import config


def truth(usages) -> tuple[float, float]:
    """(hit_rate, dollars) across usages, priced with config.PRICES."""
    read = written = uncached = 0
    dollars = 0.0
    for u in usages:
        r, w = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        w_1h = u.cache_creation.ephemeral_1h_input_tokens if u.cache_creation else 0
        read, written, uncached = read + r, written + w, uncached + u.input_tokens
        dollars += (u.input_tokens * config.PRICES["input"] + (w - w_1h) * config.PRICES["cache_write_5m"]
                    + w_1h * config.PRICES["cache_write_1h"] + r * config.PRICES["cache_read"]
                    + u.output_tokens * config.PRICES["output"])
    return read / (read + written + uncached), dollars
