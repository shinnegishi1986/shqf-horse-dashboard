import sqlite3
import random
import string
import os
import sys

DB_PATH = 'data/horse_checklist_app.db'

def generate_invitation_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def create_invitation_codes_batch(n, length=8):
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    codes = []
    while len(codes) < n:
        code = generate_invitation_code(length)
        try:
            cursor.execute("INSERT INTO invitation_codes (code, used) VALUES (?, 0)", (code,))
            codes.append(code)
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    conn.close()
    return codes

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python generate_invitation_codes.py <number_of_codes>")
        sys.exit(1)
    try:
        num_codes = int(sys.argv[1])
        if num_codes <= 0:
            raise ValueError
    except ValueError:
        print("Please provide a positive integer for the number of codes to generate.")
        sys.exit(1)

    batch_codes = create_invitation_codes_batch(num_codes)
    print(f"Invitation codes generated ({num_codes}):")
    for code in batch_codes:
        print(code)
