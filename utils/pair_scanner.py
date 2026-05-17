
def get_symbol_precision(client, symbol: str) -> dict:
    """
    Ambil presisi quantity dan price dari Binance.
    Return: {"qty_precision": int, "price_precision": int, "min_qty": float}
    """
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                qty_precision   = 0
                price_precision = s.get("pricePrecision", 2)
                min_qty         = 0.0
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step    = f["stepSize"]
                        min_qty = float(f["minQty"])
                        if "." in step:
                            qty_precision = len(step.rstrip("0").split(".")[1])
                        else:
                            qty_precision = 0
                return {
                    "qty_precision"  : qty_precision,
                    "price_precision": price_precision,
                    "min_qty"        : min_qty,
                }
    except:
        pass
    return {"qty_precision": 1, "price_precision": 2, "min_qty": 0.1}
