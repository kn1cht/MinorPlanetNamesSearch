import sqlite3
conn = sqlite3.connect('data/mpnames.sqlite3')
for row in conn.execute("SELECT name FROM sqlite_schema"):
    print(row[0])
