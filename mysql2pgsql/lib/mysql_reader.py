from __future__ import with_statement, absolute_import

import re
from contextlib import closing

import MySQLdb
import MySQLdb.cursors


re_column_length = re.compile(r'\((\d+)\)')
re_column_precision = re.compile(r'\((\d+),(\d+)\)')
re_key_1 = re.compile(r'CONSTRAINT `(\w+)` FOREIGN KEY \(`(\w+)`\) REFERENCES `(\w+)` \(`(\w+)`\)')
re_key_2 = re.compile(r'KEY `(\w+)` \((.*)\)')
re_key_3 = re.compile(r'PRIMARY KEY +\((.*)\)')


class DB:
    """
    Class that wraps MySQLdb functions that auto reconnects
    thus (hopefully) preventing the frustrating
    "server has gone away" error. Also adds helpful
    helper functions.
    """
    conn = None

    def __init__(self, options):
        args = {
            'user': str(options.get('username', 'root')),
            'db': options['database'],
            'use_unicode': True,
            'charset': 'utf8',
            }

        if options.get('password', None):
            args['passwd'] = str(options.get('password', None))

        if options.get('socket', None):
            args['unix_socket'] = str(options['socket'])
        else:
            args['host'] = str(options.get('hostname', 'localhost'))
            args['port'] = options.get('port', 3306)
            args['compress'] = options.get('compress', True)

        self.options = args

    def connect(self):
        self.conn = MySQLdb.connect(**self.options)

    def close(self):
        self.conn.close()

    def cursor(self, cursorclass=MySQLdb.cursors.Cursor):
        try:
            return self.conn.cursor(cursorclass)
        except (AttributeError, MySQLdb.OperationalError):
            self.connect()
            return self.conn.cursor(cursorclass)

    def list_tables(self):
        return self.query('SHOW TABLES;')

    def query(self, sql, args=(), one=False, large=False):
        return self.query_one(sql, args) if one\
            else self.query_many(sql, args, large)

    def query_one(self, sql, args):
        with closing(self.cursor()) as cur:
            cur.execute(sql, args)
            return cur.fetchone()

    def query_many(self, sql, args, large):
        with closing(self.cursor(MySQLdb.cursors.SSCursor if large else MySQLdb.cursors.Cursor)) as cur:
            cur.execute(sql, args)
            for row in cur:
                yield row


class MysqlReader(object):

    class Table(object):
        def __init__(self, reader, name):
            self.reader = reader
            self._name = name
            self._indexes = []
            self._foreign_keys = []
            self._triggers = []
            self._columns = self._load_columns()
            self._comment = self._load_table_comment()
            self._load_indexes()
            self._load_triggers()

        def _convert_type(self, data_type):
            """Normalize MySQL `data_type`"""
            if data_type.startswith('varchar'):
                return 'varchar'
            elif data_type.startswith('char'):
                return 'char'
            elif data_type in ('bit(1)', 'tinyint(1)', 'tinyint(1) unsigned'):
                return 'boolean'
            elif re.search(r'^smallint.* unsigned', data_type) or data_type.startswith('mediumint'):
                return 'integer'
            elif data_type.startswith('smallint'):
                return 'tinyint'
            elif data_type.startswith('tinyint') or data_type.startswith('year('):
                return 'tinyint'
            elif data_type.startswith('bigint') and 'unsigned' in data_type:
                return 'numeric'
            elif re.search(r'^int.* unsigned', data_type) or \
                    (data_type.startswith('bigint') and 'unsigned' not in data_type):
                return 'bigint'
            elif data_type.startswith('int'):
                return 'integer'
            elif data_type.startswith('float'):
                return 'float'
            elif data_type.startswith('decimal'):
                return 'decimal'
            elif data_type.startswith('double'):
                return 'double precision'
            else:
                return data_type

        def _load_columns(self):
            fields = []
            for row in self.reader.db.query('SHOW FULL COLUMNS FROM `%s`' % self.name):
                res = ()
                for field in row:
                  if type(field) == unicode:
                    res += field.encode('utf8'),
                  else:
                    res += field,
                length_match = re_column_length.search(res[1])
                precision_match = re_column_precision.search(res[1])
                length = length_match.group(1) if length_match else \
                    precision_match.group(1) if precision_match else None
                name = res[0]
                comment = res[8]
                field_type = self._convert_type(res[1])
                desc = {
                    'name': name,
                    'table_name': self.name,
                    'type': field_type,
                    'length': int(length) if length else None,
                    'decimals': precision_match.group(2) if precision_match else None,
                    'null': res[3] == 'YES' or field_type.startswith('enum') or field_type in ('date', 'datetime', 'timestamp'),
                    'primary_key': res[4] == 'PRI',
                    'auto_increment': res[6] == 'auto_increment',
                    'default': res[5] if not res[5] == 'NULL' else None,
                    'comment': comment,
                    'select': '`%s`' % name if not field_type.startswith('enum') else
                        'CASE `%(name)s` WHEN "" THEN NULL ELSE `%(name)s` END' % {'name': name},
                    }
                fields.append(desc)

            for field in (f for f in fields if f['auto_increment']):
                res = self.reader.db.query('SELECT MAX(`%s`) FROM `%s`;' % (field['name'], self.name), one=True)
                field['maxval'] = int(res[0]) if res[0] else 0

            return fields

        def _load_table_comment(self):
            table_status = self.reader.db.query('SHOW TABLE STATUS WHERE Name="%s"' % self.name, one=True)
            comment = table_status[17]
            return comment

          
        def _load_indexes(self):
            explain = self.reader.db.query('SHOW CREATE TABLE `%s`' % self.name, one=True)
            explain = explain[1]
            for line in explain.split('\n'):
                if ' KEY ' not in line:
                    continue
                index = {}
                match_data = re_key_1.search(line)
                if match_data:
                    index['name'] = match_data.group(1)
                    index['column'] = match_data.group(2)
                    index['ref_table'] = match_data.group(3)
                    index['ref_column'] = match_data.group(4)
                    self._foreign_keys.append(index)
                    continue
                match_data = re_key_2.search(line)
                if match_data:
                    index['name'] = match_data.group(1)
                    index['columns'] = [re.search(r'`(\w+)`', col).group(1) for col in match_data.group(2).split(',')]
                    index['unique'] = 'UNIQUE' in line
                    self._indexes.append(index)
                    continue
                match_data = re_key_3.search(line)
                if match_data:
                    index['primary'] = True
                    index['columns'] = [re.sub(r'\(\d+\)', '', col.replace('`', '')) for col in match_data.group(1).split(',')]
                    self._indexes.append(index)
                    continue

        def _load_triggers(self):
            explain = self.reader.db.query('SHOW TRIGGERS WHERE `table` = \'%s\'' % self.name)
            for row in explain:
                if type(row) is tuple:
                    trigger = {}
                    trigger['name'] = row[0]
                    trigger['event'] = row[1]
                    trigger['statement'] = row[3]
                    trigger['timing'] = row[4]

                    trigger['statement'] = re.sub('^BEGIN', '', trigger['statement'])
                    trigger['statement'] = re.sub('^END', '', trigger['statement'], flags=re.MULTILINE)
                    trigger['statement'] = re.sub('`', '', trigger['statement'])

                    self._triggers.append(trigger)

        @property
        def name(self):
            return self._name

        @property
        def columns(self):
            return self._columns

        @property
        def comment(self):
            return self._comment

        @property
        def indexes(self):
            return self._indexes

        @property
        def foreign_keys(self):
            return self._foreign_keys

        @property
        def triggers(self):
            return self._triggers

        @property
        def query_for(self):
            return 'SELECT %(column_names)s FROM `%(table_name)s`' % {
                'table_name': self.name,
                'column_names': ', '. join(c['select'] for c in self.columns)}

    def __init__(self, options):
        self.db = DB(options)

    @property
    def tables(self):
        return (self.Table(self, t[0]) for t in self.db.list_tables())

    def read(self, table):
        return self.db.query(table.query_for, large=True)

    def close(self):
        self.db.close()
