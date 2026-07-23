from packages.market_data.symbol_registry import SymbolRegistry, symbol_registry


def test_symbol_normalization():
    reg = SymbolRegistry()
    assert reg.normalize("BTCUSDT") == "BTC/USDT"
    assert reg.normalize("ETHUSDT") == "ETH/USDT"
    assert reg.normalize("SOLUSDT") == "SOL/USDT"


def test_to_exchange_symbol():
    reg = SymbolRegistry()
    assert reg.to_exchange_symbol("BTC/USDT") == "BTCUSDT"
    assert reg.to_exchange_symbol("ETH/USDT") == "ETHUSDT"


def test_registry_lookup():
    info = symbol_registry.get_symbol_info("BTC/USDT")
    assert info is not None
    assert info.canonical_symbol == "BTC/USDT"
    assert info.exchange_symbol == "BTCUSDT"
    assert info.base_asset == "BTC"
    assert info.quote_asset == "USDT"
