# accounts_reader.py
from openpyxl import load_workbook

def load_accounts(excel_path):
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active  # 默认第一张表
    accounts = []
    for row in ws.iter_rows(min_row=2, values_only=True):  # 跳过表头
        seq, email, password, recovery = row
        accounts.append({
            "seq": int(seq),
            "email": str(email),
            "password": str(password),
            "recovery": str(recovery),
        })
    wb.close()
    return accounts
