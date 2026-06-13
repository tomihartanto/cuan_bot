import sys
import os

# Set Python path to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from bot.exchange import create_exchange, get_balance, fetch_ticker_price, get_usdt_idr_rate
from config import Config

def main():
    print("Checking real balance on Tokocrypto...")
    try:
        exchange = create_exchange()
        bal = get_balance(exchange)
        
        idr = bal["idr"]
        holdings = bal["holdings"]
        
        print("\n=== BALANCE SUMMARY ===")
        print(f"IDR Free : Rp {idr['free']:,.2f}")
        print(f"IDR Used : Rp {idr['used']:,.2f}")
        print(f"IDR Total: Rp {idr['total']:,.2f}")
        
        has_holdings = False
        if holdings:
            usdt_idr = get_usdt_idr_rate()
            total_holdings_value_idr = 0.0
            
            for asset, amt in holdings.items():
                qty = amt['total']
                if qty <= 0.000001:  # ignore tiny dust
                    continue
                
                if not has_holdings:
                    print("\n=== HOLDINGS ===")
                    print(f"Current USDT/IDR Rate: Rp {usdt_idr:,.2f}\n")
                    has_holdings = True
                
                # Fetch price
                pair = f"{asset}/{Config.BASE_CURRENCY}"
                price = fetch_ticker_price(exchange, pair)
                
                # Fallback to USDT price if IDR pair price not found
                if price <= 0:
                    try:
                        ticker = exchange.fetch_ticker(f"{asset}/USDT")
                        price = (ticker.get("last") or ticker.get("close") or 0) * usdt_idr
                    except Exception:
                        pass
                
                value_idr = qty * price
                total_holdings_value_idr += value_idr
                
                print(f"- {asset}:")
                print(f"  Qty Total: {qty:.6f} (Free: {amt['free']:.6f}, Used: {amt['used']:.6f})")
                if price > 0:
                    print(f"  Est. Price: Rp {price:,.2f}")
                    print(f"  Est. Value: Rp {value_idr:,.2f}")
                else:
                    print("  Est. Price: Unknown")
            
            if has_holdings:
                grand_total = idr['total'] + total_holdings_value_idr
                print("\n=== TOTAL PORTFOLIO VALUE ===")
                print(f"Grand Total: Rp {grand_total:,.2f}")
        
        if not has_holdings:
            print("\nNo cryptocurrency holdings found.")
            
    except Exception as e:
        print(f"Error checking balance: {e}")

if __name__ == "__main__":
    main()
