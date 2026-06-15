import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from bot.exchange import get_balance, fetch_ticker_price
from config import Config

def main():
    print("Checking real balance on Tokocrypto...")
    try:
        bal = get_balance()

        quote_bal = bal["quote"]
        holdings  = bal["holdings"]

        print(f"\n=== BALANCE SUMMARY ===")
        print(f"{Config.BASE_CURRENCY} Free : Rp {quote_bal['free']:,.2f}")
        print(f"{Config.BASE_CURRENCY} Used : Rp {quote_bal['used']:,.2f}")
        print(f"{Config.BASE_CURRENCY} Total: Rp {quote_bal['total']:,.2f}")

        has_holdings = False
        if holdings:
            total_value = 0.0

            for asset, amt in holdings.items():
                qty = amt['total']
                if qty <= 0.000001:
                    continue

                if not has_holdings:
                    print(f"\n=== HOLDINGS ===")
                    has_holdings = True

                pair = f"{asset}/{Config.BASE_CURRENCY}"
                price = fetch_ticker_price(pair)
                value_idr = qty * price
                total_value += value_idr

                print(f"- {asset}:")
                print(f"  Qty Total: {qty:.6f} (Free: {amt['free']:.6f}, Used: {amt['used']:.6f})")
                if price > 0:
                    print(f"  Est. Price: Rp {price:,.2f}")
                    print(f"  Est. Value: Rp {value_idr:,.2f}")
                else:
                    print(f"  Est. Price: Unknown")

            if has_holdings:
                grand = quote_bal['total'] + total_value
                print(f"\n=== TOTAL PORTFOLIO VALUE ===")
                print(f"Grand Total: Rp {grand:,.2f}")

        if not has_holdings:
            print("\nNo cryptocurrency holdings found.")

    except Exception as e:
        print(f"Error checking balance: {e}")

if __name__ == "__main__":
    main()
