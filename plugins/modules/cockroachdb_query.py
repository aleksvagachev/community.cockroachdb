#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2021, Andrew Klychkov (@Andersson007) <aaklychkov@mail.ru>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cockroachdb_query

short_description: Run queries in a CockroachDB database

description:
  - Runs arbitrary queries in a CockroachDB database.

version_added: '0.1.0'

author
  - Andrew Klychkov (@Andersson007)

extends_documentation_fragment:
  - community.cockroachdb.cockroachdb_query

notes:
  - Does not support C(check_mode).

options:
  query:
    description:
    - SQL query to run. Variables can be escaped with psycopg2 syntax
      U(http://initd.org/psycopg/docs/usage.html).
    type: str

  positional_args:
    description:
    - List of values to be passed as positional arguments to the query.
    - Mutually exclusive with I(named_args).
    type: list
    elements: raw

  named_args:
    description:
    - Dictionary of key-value arguments to pass to the query.
    - Mutually exclusive with I(positional_args).
    type: dict
'''

EXAMPLES = r'''
- name: Run simple select query in acme db
  community.cockroachdb.cockroachdb_query:
    db: acme
    query: SELECT version()
  register: result

- name: Print information returned from the previous task
  ansible.builtin.debug:
    var: result
    verbosity: 2

- name: Run query in acme db using positional args and non-default credentials
  community.cockroachdb.cockroachdb_query:
    db: acme
    login_user: django
    login_password: mysecretpass
    query: SELECT * FROM acme WHERE id = %s AND story = %s
    positional_args:
    - 1
    - test

- name: Run query in test_db using named args
  community.cockroachdb.cockroachdb_query:
    db: test_db
    query: SELECT * FROM test WHERE id = %(id_val)s AND story = %(story_val)s
    named_args:
      id_val: 1
      story_val: test
'''

RETURN = r'''
query:
    description:
    - Executed query containing substituted arguments.
    returned: always
    type: str
    sample: 'SELECT * FROM bar'

statusmessage:
  description:
    - Attribute containing the message returned by the command.
  returned: always
  type: str
  sample: 'INSERT 0 1'

query_result:
  description:
    - List of lists representing returned rows.
  returned: always
  type: list
  elements: dict
  sample: []

rowcount:
  description:
    - Number of produced or affected rows.
  returned: changed
  type: int
  sample: 5
'''

import datetime
import decimal

try:
    from psycopg2 import ProgrammingError as Psycopg2ProgrammingError
except ImportError:
    # it is needed for checking 'no result to fetch' in main(),
    # psycopg2 availability will be checked by connect_to_db() into
    # ansible.module_utils.postgres
    pass

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native

from ansible_collections.community.cockroachdb.plugins.module_utils.cockroachdb import (
    common_argument_spec,
    CockroachDB,
    get_conn_params,
)

TYPES_NEED_TO_CONVERT = (decimal.Decimal, datetime.timedelta)


def convert_to_supported(val):
    """Convert unsupported type to appropriate.

    Args:
        val (any) -- Any value fetched from database.

    Returns value of appropriate type.
    """
    if isinstance(val, decimal.Decimal):
        return float(val)

    elif isinstance(val, datetime.timedelta):
        return str(val)

    return val  # By default returns the same value


def fetch_from_cursor(cursor):
    """Fetch rows from cursor handling unsupported types.

    Args:
        cursor (cursor): Cursor object of a database Python connector.

    Returns query_result list.
    """
    query_result = []
    for row in cursor:
        # Ansible engine does not support some types like decimals and timedelta.
        # An explicit conversion is required on the module's side.
        for i, elem in enumerate(row):
            if type(elem) in TYPES_NEED_TO_CONVERT:
                row = list(row)
                row[i] = convert_to_supported(elem)

        query_result.append(row)

    return query_result


def get_args(positional_args, named_args):
    """Get arguments to pass them to cursor.execute() later.

    They are mutually exclusive, so at least one of them is always None.

    Returns one of passed arguments which is not None or None.
    """
    if positional_args:
        return positional_args
    elif named_args:
        return named_args
    else:
        return None


def execute(module, cursor, query, args):
    """Execute query in CockroachDB database.

    Args:
        module (AnsibleModule) -- Object of ansible.module_utils.basic.AnsibleModule class.
        cursor (cursor): Cursor object of a database Python connector.
        query (str) -- Query to execute.
        args (dict|tuple) -- Data structure to pass to cursor.execute as query parameters.

    Returns a tuple (
        statusmessage (str) -- Status message returned by psycopg2, for example, "SELECT 1".
        rowcount (int) -- Number of rows fetched, for example, 1.
        query_result (list) -- List that contains lists [[col1_val, col2_val, ...], [...]].
    )
    """
    statusmessage = None
    rowcount = None
    query_result = []
    try:
        mogrified_query = cursor.mogrify(query, args)
        cursor.execute(query, args)
        statusmessage = cursor.statusmessage
        rowcount = cursor.rowcount

        try:
            query_result = fetch_from_cursor(cursor)

        except Psycopg2ProgrammingError as e:
            if to_native(e) == 'no results to fetch':
                pass

        except Exception as e:
            module.fail_json(msg='Cannot fetch rows from cursor: %s' % to_native(e))

    except Exception as e:
        module.fail_json(msg='Cannot execute query "%s": %s' % (query, to_native(e)))

    return statusmessage, rowcount, mogrified_query, query_result


def main():
    # Set up arguments
    argument_spec = common_argument_spec()
    argument_spec.update(
        query=dict(type='str'),
        positional_args=dict(type='list', elements='raw'),
        named_args=dict(type='dict'),
    )

    # Instantiate an object of module class
    module = AnsibleModule(
        argument_spec=argument_spec,
        mutually_exclusive=(('positional_args', 'named_args'),),
        supports_check_mode=False,
    )

    # Assign passed options to variables
    query = module.params['query']
    positional_args = module.params['positional_args']
    named_args = module.params['named_args']

    # Connect to DB, get cursor
    cockroachdb = CockroachDB(module)
    conn = cockroachdb.connect(conn_params=get_conn_params(module.params),
                               autocommit=True)
    cursor = conn.cursor()

    # Prepare args:
    args = get_args(positional_args, named_args)

    # Execute query
    statusmsg, rowcount, query, query_result = execute(module, cursor, query, args)

    # Close cursor and conn
    try:
        cursor.close()
        conn.close()
    except Exception:
        pass

    # Users will get this in JSON output after execution
    kw = dict(
        changed=True,
        statusmessage=statusmsg,
        rowcount=rowcount,
        query_result=query_result,
        query=query,
    )

    module.exit_json(**kw)


if __name__ == '__main__':
    main()
