import sqlite3
import sys

def dump_sorted(db_path, out_path):
    schema_lines = []
    insert_lines = []
    trigger_lines = []

    conn = sqlite3.connect(db_path)
    for line in conn.iterdump():
        if (line.startswith('BEGIN') or 
            line.startswith('COMMIT') or 
            line.startswith('PRAGMA') or 
            line.startswith('SAVEPOINT') or 
            line.startswith('RELEASE')):
            continue
            
        # Skip sqlite internal tables and FTS shadow tables
        if 'sqlite_sequence' in line or 'sqlite_master' in line:
            continue
        if 'minor_planets_fts' in line:
            continue
        if 'CREATE TRIGGER minor_planets_a' in line:
            continue

        if line.startswith('INSERT'):
            insert_lines.append(line)
        elif line.startswith('CREATE TRIGGER') or line.startswith('CREATE INDEX'):
            trigger_lines.append(line)
        else:
            schema_lines.append(line)

    def prio(x):
        if x.startswith('CREATE TABLE minor_planets ') or x.startswith('CREATE TABLE "minor_planets"'): return 0
        if x.startswith('INSERT INTO "minor_planets"'): return 0
        if x.startswith('CREATE TABLE categories') or x.startswith('CREATE TABLE "categories"'): return 1
        if x.startswith('INSERT INTO "categories"'): return 1
        if x.startswith('CREATE TABLE discovery_facets') or x.startswith('CREATE TABLE "discovery_facets"'): return 2
        if x.startswith('INSERT INTO "discovery_facets"'): return 2
        return 3

    schema_lines.sort(key=prio)
    insert_lines.sort(key=prio)

    with open(out_path, 'w', encoding='utf-8') as f:
        # A D1 import is a full snapshot replacement.  Drop only tables owned by
        # this application; do not touch Cloudflare-managed tables such as _cf_KV.
        # The FTS virtual table must be dropped before its content table, and
        # foreign keys are disabled while the interdependent tables are replaced.
        f.write('''
PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS minor_planets_fts;
DROP TABLE IF EXISTS classification_assignments;
DROP TABLE IF EXISTS classification_jobs;
DROP TABLE IF EXISTS citation_facets;
DROP TABLE IF EXISTS discovery_facets;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS naming_publications;
DROP TABLE IF EXISTS wgsbn_bulletins;
DROP TABLE IF EXISTS identifier_cache;
DROP TABLE IF EXISTS ingest_runs;
DROP TABLE IF EXISTS minor_planets;
''')
        for l in schema_lines: f.write(l + '\n')
        for l in insert_lines: f.write(l + '\n')
        for l in trigger_lines: f.write(l + '\n')

        # These indexes must be present in D1 even when the source SQLite file
        # predates the current application schema.
        f.write('''
CREATE INDEX IF NOT EXISTS categories_kind_value_permid
ON categories(kind, value, permid);
CREATE INDEX IF NOT EXISTS discovery_facets_kind_value_permid
ON discovery_facets(kind, value, permid);
CREATE INDEX IF NOT EXISTS minor_planets_is_neo_permid
ON minor_planets(is_neo, permid);
CREATE INDEX IF NOT EXISTS minor_planets_is_pha_permid
ON minor_planets(is_pha, permid);
PRAGMA optimize;
''')
        
        # Append FTS table creation and triggers
        f.write('''
CREATE VIRTUAL TABLE minor_planets_fts USING fts5(
    permid,
    packed_permid,
    iau_designation,
    name_ascii,
    name_display,
    citation_text,
    discovery_site,
    discoverer_text,
    content='minor_planets',
    content_rowid='rowid',
    tokenize='trigram'
);
CREATE TRIGGER minor_planets_ai AFTER INSERT ON minor_planets BEGIN
    INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
    VALUES (new.rowid, new.permid, new.packed_permid, new.iau_designation, new.name_ascii, new.name_display, new.citation_text, new.discovery_site, new.discoverer_text);
END;
CREATE TRIGGER minor_planets_ad AFTER DELETE ON minor_planets BEGIN
    INSERT INTO minor_planets_fts(minor_planets_fts, rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
    VALUES('delete', old.rowid, old.permid, old.packed_permid, old.iau_designation, old.name_ascii, old.name_display, old.citation_text, old.discovery_site, old.discoverer_text);
END;
CREATE TRIGGER minor_planets_au AFTER UPDATE ON minor_planets BEGIN
    INSERT INTO minor_planets_fts(minor_planets_fts, rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
    VALUES('delete', old.rowid, old.permid, old.packed_permid, old.iau_designation, old.name_ascii, old.name_display, old.citation_text, old.discovery_site, old.discoverer_text);
    INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
    VALUES (new.rowid, new.permid, new.packed_permid, new.iau_designation, new.name_ascii, new.name_display, new.citation_text, new.discovery_site, new.discoverer_text);
END;
INSERT INTO minor_planets_fts(minor_planets_fts) VALUES('rebuild');
''')


    print(f'Schemas: {len(schema_lines)}, Inserts: {len(insert_lines)}, Triggers: {len(trigger_lines)}')

if __name__ == '__main__':
    dump_sorted(sys.argv[1], sys.argv[2])
