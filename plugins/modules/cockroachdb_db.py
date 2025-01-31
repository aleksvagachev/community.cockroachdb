#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2022, Andrew Klychkov (@Andersson007) <aaklychkov@mail.ru>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cockroachdb_db
short_description: Create, modify or delete a CockroachDB database
description:
  - Creates, modifies or deletes a CockroachDB database.
version_added: '0.3.0'
author:
  - Andrew Klychkov (@Andersson007)
  - Aleksandr Vagachev (@aleksvagachev)
extends_documentation_fragment:
  - community.cockroachdb.cockroachdb
notes:
  - Supports C(check_mode).
options:
  name:
    description: Database name to create, modify or delete.
    type: str
    required: yes
  state:
    description:
    - If C(present), creates if it does not exist or modifies it.
    - If C(absent), deletes the database.
    type: str
    choices: [absent, present]
    default: present
  owner:
    description: Database owner.
    type: str
'''

EXAMPLES = r'''
# Connect in the verify-full SSL mode to the acme database
# and create the test_db database
- name: Create test_db database
  community.cockroachdb.cockroachdb_db:
    login_host: 192.168.0.10
    login_db: acme
    ssl_mode: verify-full
    ssl_root_cert: /tmp/certs/ca.crt
    ssl_cert: /tmp/certs/client.root.crt
    ssl_key: /tmp/certs/client.root.key
    name: test_db

- name: Drop test_db database
  community.cockroachdb.cockroachdb_db:
    login_host: 192.168.0.10
    login_db: acme
    state: absent
    name: test_db

- name: Change owner from test_db database
  community.cockroachdb.cockroachdb_db:
    login_host: 192.168.0.10
    login_db: acme
    name: test_db
    owner: test_user
'''

RETURN = r'''#'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.community.cockroachdb.plugins.module_utils.cockroachdb import (
    common_argument_spec,
    CockroachDBServer,
    get_conn_params,
)

executed_statements = []


class CockroachDBDatabase():
    def __init__(self, module, cursor, name):
        self.module = module
        self.cursor = cursor
        self.name = name
        # Defaults
        self.exists = False
        self.primary_region = None
        self.regions = []
        self.survive_failure = None
        self.owner = None
        # Update the above by fetching
        # the info from the database
        self.__fetch_info()

    def __fetch_info(self):
        self.cursor.execute('SHOW DATABASES')
        res = self.cursor.fetchall()
        for d in res:
            if d['database_name'] == self.name:
                self.exists = True
                self.owner = d['owner']
                self.primary_region = d['primary_region']
                self.regions = d['regions']
                self.survive_failure = d['survival_goal']

    def create(self):
        if self.module.check_mode:
            return

        query = 'CREATE DATABASE "%s"' % self.name
        if self.module.params['owner']:
            query += 'OWNER %s' % (self.module.params['owner'])
        
        self.cursor.execute(query)
        executed_statements.append((query, ()))

    def drop(self):
        if self.module.check_mode:
            return True

        query = 'DROP DATABASE "%s"' % self.name
        self.cursor.execute(query)
        executed_statements.append((query, ()))

    def modify(self, owner, target):
        changed = False

        # Change owner
        if owner:
            if self.module.check_mode:
                return True
            self.__change_owner(owner)
            changed = True

        return changed

    def __change_owner(self, new_owner):
        query = 'ALTER DATABASE "%s" OWNER TO %s' % (self.name, new_owner)
        self.cursor.execute(query)
        executed_statements.append((query, ()))


def main():
    # Set up arguments
    # We keep arguments common for all modules (like connection-related)
    # in a dict returned by plugins.module_utils.cockroachdb.common_argument_spec
    argument_spec = common_argument_spec()

    # Then we add arguments specific to this module
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', choices=['absent', 'present'], default='present'),
        owner=dict(type='str'),
        target=dict(type='str'),
    )

    # Instantiate an object of module class
    # which is an interface we use to interact with ansible-core
    # from the module (e.g., it'll check if a user passed only acceptable arguments
    # and their acceptable values, we can show warnings to users,
    # we can gracefully fail when we need, and, at the end, we can return values to users)
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    # Assign passed options to variables
    name = module.params['name']
    state = module.params['state']
    owner = module.params['owner']
    target = module.params['target']

    # Set defaults
    changed = False

    # Connect to DB, get cursor
    cockroachdb = CockroachDBServer(module)

    conn = cockroachdb.connect(conn_params=get_conn_params(module.params),
                               autocommit=True, rows_type='dict')
    cursor = conn.cursor()

    # Instantiate the main object of the module
    database = CockroachDBDatabase(module, cursor, name)

    # Do job
    if state == 'present':
        if not database.exists:
            database.create()
            changed = True
        else:
            changed = database.modify(owner, target)
    else:
        # When state is absent
        if database.exists:
            database.drop()
            changed = True

    # Close cursor and conn
    cursor.close()
    conn.close()

    # Users will get this in JSON output after execution
    kw = dict(
        changed=changed,
        executed_statements=executed_statements,
    )

    # Return values and exit
    module.exit_json(**kw)


if __name__ == '__main__':
    main()
