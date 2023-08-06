from __future__ import absolute_import

import re
from cStringIO import StringIO
from datetime import date, datetime, timedelta

from psycopg2.extensions import AsIs, Binary, QuotedString
from pytz import timezone


class PostgresWriter(object):
    """Base class for :py:class:`mysql2pgsql.lib.postgres_file_writer.PostgresFileWriter`
    and :py:class:`mysql2pgsql.lib.postgres_db_writer.PostgresDbWriter`.
    """

    def __init__(self, index_prefix, tz=False):
        self.column_types = {}
        self.index_prefix = index_prefix if index_prefix else ''
        if tz:
            self.tz = timezone('UTC')
            self.tz_offset = '+00:00'
        else:
            self.tz = None
            self.tz_offset = ''

    def column_description(self, column):
        return '"%s" %s' % (column['name'], self.column_type_info(column))

    def column_type(self, column):
        hash_key = hash(frozenset(column.items()))
        self.column_types[hash_key] = self.column_type_info(column).split(" ")[0]
        return self.column_types[hash_key]

    def column_type_info(self, column):
        """
        """
        null = "" if column['null'] else " NOT NULL"

        def get_type(column):
            """This in conjunction with :py:class:`mysql2pgsql.lib.mysql_reader.MysqlReader._convert_type`
            determines the PostgreSQL data type. In my opinion this is way too fugly, will need
            to refactor one day.
            """
            t = lambda v: not v == None
            default = (' DEFAULT %s' % QuotedString(column['default']).getquoted()) if t(column['default']) else None

            if column['type'] == 'char':
                default = ('%s::char' % default) if t(default) else None
                return default, 'character(%s)' % column['length']
            elif column['type'] == 'varchar':
                default = ('%s::character varying' % default) if t(default) else None
                return default, 'character varying(%s)' % column['length']
            elif column['type'] == 'integer':
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'integer'
            elif column['type'] == 'bigint':
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'bigint'
            elif column['type'] == 'tinyint':
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'smallint'
            elif column['type'] == 'boolean':
                default = (" DEFAULT %s" % ('true' if int(column['default']) == 1 else 'false')) if t(default) else None
                return default, 'boolean'
            elif column['type'] == 'float':
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'real'
            elif column['type'] == 'float unsigned':
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'real'
            elif column['type'] in ('numeric', 'decimal'):
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'numeric(%s, %s)' % (column['length'] or 20, column['decimals'] or 0)
            elif column['type'] == 'double precision':
                default = (" DEFAULT %s" % (column['default'] if t(column['default']) else 'NULL')) if t(default) else None
                return default, 'double precision'
            elif column['type'] == 'datetime' or column['type'].startswith('datetime('):
                default = None
                if self.tz:
                    return default, 'timestamp with time zone'
                else:
                    return default, 'timestamp without time zone'
            elif column['type'] == 'date':
                default = None
                return default, 'date'
            elif column['type'] == 'timestamp':
                if column['default'] == None:
                    default = None
                elif "current_timestamp()" in column['default']:
                    default = ' DEFAULT CURRENT_TIMESTAMP'
                elif "CURRENT_TIMESTAMP" in column['default']:
                    default = ' DEFAULT CURRENT_TIMESTAMP'
                elif "0000-00-00 00:00" in column['default']:
                    if self.tz:
                        default = " DEFAULT '1970-01-01T00:00:00.000000%s'" % self.tz_offset
                    elif "0000-00-00 00:00:00" in column['default']:
                        default = " DEFAULT '1970-01-01 00:00:00'"
                    else:
                        default = " DEFAULT '1970-01-01 00:00'"
                if self.tz:
                    return default, 'timestamp with time zone'
                else:
                    return default, 'timestamp without time zone'
            elif column['type'] == 'time' or column['type'].startswith('time('):
                default = " DEFAULT NOW()" if t(default) else None
                if self.tz:
                    return default, 'time with time zone'
                else:
                    return default, 'time without time zone'
            elif column['type'] in ('blob', 'binary', 'longblob', 'mediumblob', 'tinyblob', 'varbinary'):
                return default, 'bytea'
            elif column['type'].startswith('binary(') or column['type'].startswith('varbinary('):
                return default, 'bytea'
            elif column['type'] in ('tinytext', 'mediumtext', 'longtext', 'text'):
                return default, 'text'
            elif column['type'].startswith('enum'):
                default = (' %s::character varying' % default) if t(default) else None
                enum = re.sub(r'^enum\(|\)$', '', column['type'])
                # TODO: will work for "'.',',',''''" but will fail for "'.'',','.'"
                max_enum_size = max([len(e.replace("''", "'")) for e in enum.split("','")])
                return default, ' character varying(%s) check("%s" in (%s))' % (max_enum_size, column['name'], enum)
            elif column['type'].startswith('bit('):
                return ' DEFAULT %s' % column['default'].upper() if column['default'] else column['default'], 'varbit(%s)' % re.search(r'\((\d+)\)', column['type']).group(1)
            elif column['type'].startswith('set('):
                if default:
                    default = ' DEFAULT ARRAY[%s]::text[]' % ','.join(QuotedString(
                        v).getquoted() for v in re.search(r"'(.*)'", default).group(1).split(','))
                return default, 'text[]'
            else:
                raise Exception('unknown %s' % column['type'])

        default, column_type = get_type(column)

        if column.get('auto_increment', None):
            return '%s DEFAULT nextval(\'"%s_%s_seq"\'::regclass) NOT NULL' % (
                   column_type, column['table_name'], column['name'])

        return '%s%s%s' % (column_type, (default if not default == None else ''), null)

    def table_comments(self, table):
        comments = []
        if table.comment:
            comments.append('COMMENT ON TABLE %s is %s;' % (table.name, QuotedString(table.comment).getquoted()))
        for column in table.columns:
            if column['comment']:
                comments.append('COMMENT ON COLUMN %s.%s is %s;' % (table.name, column['name'], QuotedString(column['comment']).getquoted()))
        return comments

    def process_row(self, table, row):
        """Examines row data from MySQL and alters
        the values when necessary to be compatible with
        sending to PostgreSQL via the copy command
        """
        for index, column in enumerate(table.columns):
            hash_key = hash(frozenset(column.items()))
            column_type = self.column_types[hash_key] if hash_key in self.column_types else self.column_type(column)
            if row[index] == None and ('timestamp' not in column_type or not column['default']):
                row[index] = '\N'
            elif row[index] == None and column['default']:
                if self.tz:
                    row[index] = '1970-01-01T00:00:00.000000' + self.tz_offset
                else:
                    row[index] = '1970-01-01 00:00:00'
            elif 'bit' in column_type:
                row[index] = bin(ord(row[index]))[2:]
            elif isinstance(row[index], (str, unicode, basestring)):
                if column_type == 'bytea':
                    row[index] = Binary(row[index]).getquoted()[1:-8] if row[index] else row[index]
                elif 'text[' in column_type:
                    row[index] = '{%s}' % ','.join('"%s"' % v.replace('"', r'\"') for v in row[index].split(','))
                else:
                    row[index] = row[index].replace('\\', r'\\').replace('\n', r'\n').replace(
                        '\t', r'\t').replace('\r', r'\r').replace('\0', '')
            elif column_type == 'boolean':
                # We got here because you used a tinyint(1), if you didn't want a bool, don't use that type
                row[index] = 't' if row[index] not in (None, 0) else 'f' if row[index] == 0 else row[index]
            elif isinstance(row[index], (date, datetime)):
                if isinstance(row[index], datetime) and self.tz:
                    try:
                        if row[index].tzinfo:
                            row[index] = row[index].astimezone(self.tz).isoformat()
                        else:
                            row[index] = datetime(*row[index].timetuple()[:6], tzinfo=self.tz).isoformat()
                    except Exception as e:
                        print e.message
                else:
                    row[index] = row[index].isoformat()
            elif isinstance(row[index], timedelta):
                row[index] = datetime.utcfromtimestamp(_get_total_seconds(row[index])).time().isoformat()
            else:
                row[index] = AsIs(row[index]).getquoted()

    def table_attributes(self, table):
        primary_keys = []
        serial_key = None
        maxval = None
        columns = StringIO()

        for column in table.columns:
            if column['auto_increment']:
                serial_key = column['name']
                maxval = 1 if column['maxval'] < 1 else column['maxval'] + 1
            if column['primary_key']:
                primary_keys.append(column['name'])
            columns.write('  %s,\n' % self.column_description(column))
        return primary_keys, serial_key, maxval, columns.getvalue()[:-2]

    def truncate(self, table):
        serial_key = None
        maxval = None

        for column in table.columns:
            if column['auto_increment']:
                serial_key = column['name']
                maxval = 1 if column['maxval'] < 1 else column['maxval'] + 1

        truncate_sql = 'TRUNCATE "%s" CASCADE;' % table.name
        serial_key_sql = None

        if serial_key:
            serial_key_sql = "SELECT pg_catalog.setval(pg_get_serial_sequence(%(table_name)s, %(serial_key)s), %(maxval)s, true);" % {
                'table_name': QuotedString('"%s"' % table.name).getquoted(),
                'serial_key': QuotedString(serial_key).getquoted(),
                'maxval': maxval}

        return (truncate_sql, serial_key_sql)

    def write_table(self, table):
        primary_keys, serial_key, maxval, columns = self.table_attributes(table)
        serial_key_sql = []
        table_sql = []
        if serial_key:
            serial_key_seq = '%s_%s_seq' % (table.name, serial_key)
            serial_key_sql.append('DROP SEQUENCE IF EXISTS "%s" CASCADE;' % serial_key_seq)
            serial_key_sql.append("""CREATE SEQUENCE "%s" INCREMENT BY 1
                                  NO MAXVALUE NO MINVALUE CACHE 1;""" % serial_key_seq)
            serial_key_sql.append('SELECT pg_catalog.setval(\'"%s"\', %s, true);' % (serial_key_seq, maxval))

        table_sql.append('DROP TABLE IF EXISTS "%s" CASCADE;' % table.name)
        table_sql.append('CREATE TABLE "%s" (\n%s\n)\nWITHOUT OIDS;' % (table.name.encode('utf8'), columns))
        table_sql.extend(self.table_comments(table))
        return (table_sql, serial_key_sql)

    def write_indexes(self, table):
        index_sql = []
        primary_index = [idx for idx in table.indexes if idx.get('primary', None)]
        index_prefix = self.index_prefix
        if primary_index:
            index_sql.append('ALTER TABLE "%(table_name)s" ADD CONSTRAINT "%(index_name)s_pkey" PRIMARY KEY(%(column_names)s);' % {
                'table_name': table.name,
                'index_name': '%s%s_%s' % (index_prefix, table.name,
                                           '_'.join(primary_index[0]['columns'])),
                'column_names': ', '.join('"%s"' % col for col in primary_index[0]['columns']),
            })
        for index in table.indexes:
            if 'primary' in index:
                continue
            unique = 'UNIQUE ' if index.get('unique', None) else ''
            index_name = '%s%s_%s' % (index_prefix, table.name, '_'.join(index['columns']))
            index_sql.append('DROP INDEX IF EXISTS "%s" CASCADE;' % index_name)
            index_sql.append('CREATE %(unique)sINDEX "%(index_name)s" ON "%(table_name)s" (%(column_names)s);' % {
                'unique': unique,
                'index_name': index_name,
                'table_name': table.name,
                'column_names': ', '.join('"%s"' % col for col in index['columns']),
            })

        return index_sql

    def write_constraints(self, table):
        constraint_sql = []
        for key in table.foreign_keys:
            constraint_sql.append("""ALTER TABLE "%(table_name)s" ADD FOREIGN KEY ("%(column_name)s")
            REFERENCES "%(ref_table_name)s"(%(ref_column_name)s);""" % {
                'table_name': table.name,
                'column_name': key['column'],
                'ref_table_name': key['ref_table'],
                'ref_column_name': key['ref_column']})
        return constraint_sql

    def write_triggers(self, table):
        trigger_sql = []
        for key in table.triggers:
            trigger_sql.append("""CREATE OR REPLACE FUNCTION %(fn_trigger_name)s RETURNS TRIGGER AS $%(trigger_name)s$
            BEGIN
                %(trigger_statement)s
            RETURN NULL;
            END;
            $%(trigger_name)s$ LANGUAGE plpgsql;""" % {
                'table_name': table.name,
                'trigger_time': key['timing'],
                'trigger_event': key['event'],
                'trigger_name': key['name'],
                'fn_trigger_name': 'fn_' + key['name'] + '()',
                'trigger_statement': key['statement']})

            trigger_sql.append("""CREATE TRIGGER %(trigger_name)s %(trigger_time)s %(trigger_event)s ON %(table_name)s
            FOR EACH ROW
            EXECUTE PROCEDURE fn_%(trigger_name)s();""" % {
                'table_name': table.name,
                'trigger_time': key['timing'],
                'trigger_event': key['event'],
                'trigger_name': key['name']})

        return trigger_sql

    def close(self):
        raise NotImplementedError

    def write_contents(self, table, reader):
        raise NotImplementedError

# Original fix for Py2.6: https://github.com/mozilla/mozdownload/issues/73
def _get_total_seconds(dt):
    # Keep backward compatibility with Python 2.6 which doesn't have this method
    if hasattr(datetime, 'total_seconds'):
        return dt.total_seconds()
    else:
        return (dt.microseconds + (dt.seconds + dt.days * 24 * 3600) * 10**6) / 10**6
