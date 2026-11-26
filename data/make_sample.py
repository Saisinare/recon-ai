"""Generate made-up bank and ledger files with the cases that break simple tools.

Writes data/sample/bank.csv, ledger.csv and truth.csv (the right answer, for scoring).
All names and numbers are fictional test data.
"""
import csv
import datetime as dt
import random
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent / "sample"
ledger, bank, truth = [], [], []


def D(m, d):
    return dt.date(2026, m, d)


def L(date, party, doc, amt, typ="invoice"):
    lid = f"L{len(ledger) + 1:03d}"
    ledger.append([lid, date, party, doc, typ, f"{amt:.2f}"])
    return lid


def B(date, desc, amt, ids=(), dup=False):
    bid = f"B{len(bank) + 1:03d}"
    bank.append([bid, date, desc, f"{amt:.2f}"])
    truth.append([bid, "DUP" if dup else ";".join(ids)])
    return bid


used = set()


def amount(lo, hi):
    while True:
        a = random.randint(lo, hi) * 250 / 1.0
        if a not in used:
            used.add(a)
            return a


# 1. clean receipts that quote the invoice number
customers = [("Sharma Traders Pvt Ltd", "SHARMA TRADERS"), ("Infosys Ltd", "INFOSYS LIMITED"),
             ("Kotak Logistics", "KOTAK LOGISTICS"), ("Bluestone Foods LLP", "BLUESTONE FOODS"),
             ("Verma Textiles", "VERMA TEXTILES")]
for n in range(12):
    party, bname = random.choice(customers)
    d = D(9, random.randint(1, 25))
    a = amount(20, 360)
    lid = L(d, party, f"INV-{1001 + n}", a)
    B(d + dt.timedelta(days=random.randint(8, 30)), f"NEFT/CR/{random.randint(10**9, 10**10)}/{bname}/INV-{1001 + n}", a, [lid])
dup_src = bank[2][:]

# 2. vendor bills paid with the bill number
for n, (party, bname, a) in enumerate([("Amazon Web Services", "AMAZON WEB SERVICES", 18432.60),
                                        ("Airtel Broadband", "AIRTEL", 3539.00),
                                        ("BESCOM Electricity", "BESCOM", 7260.00),
                                        ("WeWork India", "WEWORK INDIA", 54000.00)]):
    lid = L(D(9, 26 + n), party, f"BILL-{2201 + n}", -a, "bill")
    B(D(10, 3 + n), f"NEFT/DR/{random.randint(10**9, 10**10)}/{bname}/BILL-{2201 + n}", -a, [lid])

# 3. no reference, but the amount is unique
for party, desc, doc, a, d in [("Tata Consultancy Services", "IMPS/P2A/629183301/TATA CONSULTANC", "INV-1101", 118000.00, 5),
                               ("Bluestone Foods LLP", "UPI/BLUESTONE/bluestone@icici/OCT", "INV-1102", 64250.50, 7),
                               ("Verma Textiles", "IMPS/VERMA TEX/771023/SETTLEMENT", "INV-1103", 27775.25, 9)]:
    lid = L(D(9, 12), party, doc, a)
    B(D(10, d), desc, a, [lid])

# 4. abbreviation: AMZN = Amazon, and another open bill has the same amount
lid = L(D(10, 3), "Amazon India", "BILL-2207", -2499.00, "bill")
L(D(10, 2), "Airtel Broadband", "BILL-2208", -2499.00, "bill")          # stays open
B(D(10, 4), "POS 4521XXXX5512 AMZN MKTP IN", -2499.00, [lid])

# 5. name spelled differently, and another customer owes the same amount
lid = L(D(9, 20), "Mehta & Sons", "INV-1104", 15000.00)
L(D(9, 22), "Sharma Traders Pvt Ltd", "INV-1105", 15000.00)               # stays open
B(D(10, 6), "NEFT/CR/MEHTA AND SONS/OCT PMT", 15000.00, [lid])

# 6. one deposit pays three invoices, a fourth stays open
ids = [L(D(9, 5), "Reliance Retail Ltd", "INV-1106", 45000.00),
       L(D(9, 9), "Reliance Retail Ltd", "INV-1107", 32500.00),
       L(D(9, 14), "Reliance Retail Ltd", "INV-1108", 47000.00)]
L(D(10, 1), "Reliance Retail Ltd", "INV-1109", 30000.00)                  # stays open
B(D(10, 10), "NEFT/CR/RELIANCE RETAIL LTD/PAYMENT BATCH 0923", 124500.00, ids)

# 7. one payment quotes two invoices
ids = [L(D(9, 18), "Infosys Ltd", "INV-1110", 22000.00), L(D(9, 19), "Infosys Ltd", "INV-1111", 18500.00)]
B(D(10, 11), "NEFT/CR/INFOSYS LIMITED/INV-1110 INV-1111", 40500.00, ids)

# 8. payment processor payouts with a 2.9% fee taken off
ids = [L(D(10, 1), "Stripe Payments India", "INV-1112", 25000.00), L(D(10, 2), "Stripe Payments India", "INV-1113", 25000.00)]
B(D(10, 8), "ACH/STRIPE PAYOUT/PO_8823XK", 48550.00, ids)
lid = L(D(10, 18), "Stripe Payments India", "INV-1114", 18000.00)
B(D(10, 22), "ACH/STRIPE PAYOUT/PO_9154QA", 17478.00, [lid])

# 9. customer deducted 2% TDS
lid = L(D(9, 25), "Zomato Ltd", "INV-1115", 10000.00)
B(D(10, 12), "UPI/ZOMATO LTD/zomato@hdfcbank/INV-1115 TDS", 9800.00, [lid])

# 10. reference written in words
lid = L(D(9, 28), "Kotak Logistics", "INV-1117", 12340.00)
B(D(10, 14), "IMPS/KOTAK LOGI/invoice no 1117 part pmt", 12340.00, [lid])

# 11. bank feed sent the same line twice
B(dup_src[1], dup_src[2], float(dup_src[3]), dup=True)

# 12. bank-only lines and ledger-only items
B(D(10, 15), "SMS ALERT CHARGES QTR SEP26", -59.00)
B(D(10, 31), "CREDIT INTEREST CAPITALISED", 312.40)
L(D(10, 20), "Verma Textiles", "INV-1116", 8250.00)

OUT.mkdir(parents=True, exist_ok=True)
for name, header, rows in [("bank.csv", ["id", "date", "description", "amount"], sorted(bank, key=lambda r: (r[1], r[0]))),
                           ("ledger.csv", ["id", "date", "party", "doc_no", "type", "amount"], ledger),
                           ("truth.csv", ["bank_id", "ledger_ids"], truth)]:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
print(f"{len(bank)} bank lines, {len(ledger)} ledger items -> {OUT}")
