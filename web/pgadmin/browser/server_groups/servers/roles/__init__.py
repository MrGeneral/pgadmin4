##########################################################################
#
# pgAdmin 4 - PostgreSQL Tools
#
# Copyright (C) 2013 - 2016, The pgAdmin Development Team
# This software is released under the PostgreSQL Licence
#
##########################################################################
from flask import render_template, request, current_app, jsonify
from flask.ext.babel import gettext as _
from pgadmin.utils.ajax import make_json_response, \
    make_response as ajax_response, precondition_required, \
    internal_server_error, forbidden, \
    not_implemented, success_return
from pgadmin.browser.utils import NodeView
from pgadmin.browser.collection import CollectionNodeModule
import pgadmin.browser.server_groups as sg
from pgadmin.utils.driver import get_driver
from config import PG_DEFAULT_DRIVER
import re
import datetime
from functools import wraps
import simplejson as json


class RoleModule(CollectionNodeModule):
    NODE_TYPE = 'role'
    COLLECTION_LABEL = _("Login/Group Roles")

    def __init__(self, *args, **kwargs):
        self.min_ver = None
        self.max_ver = None

        super(RoleModule, self).__init__(*args, **kwargs)

    def get_nodes(self, gid, sid):
        """
        Generate the collection node
        """

        yield self.generate_browser_collection_node(sid)

    @property
    def node_inode(self):
        """
        Override this property to make the node as leaf node.
        """
        return False

    @property
    def script_load(self):
        """
        Load the module script for server, when any of the server-group node is
        initialized.
        """
        return sg.ServerGroupModule.NODE_TYPE

    @property
    def csssnippets(self):
        """
        Returns a snippet of css to include in the page
        """
        snippets = [
                render_template(
                    "browser/css/collection.css",
                    node_type=self.node_type
                    ),
                render_template("role/css/role.css")]

        for submodule in self.submodules:
            snippets.extend(submodule.csssnippets)

        return snippets


blueprint = RoleModule(__name__)


class RoleView(NodeView):
    node_type = 'role'

    parent_ids = [
            {'type': 'int', 'id': 'gid'},
            {'type': 'int', 'id': 'sid'}
            ]
    ids = [
            {'type': 'int', 'id': 'rid'}
            ]

    operations = dict({
        'obj': [
            {'get': 'properties', 'delete': 'drop', 'put': 'update'},
            {'get': 'list', 'post': 'create'}
        ],
        'nodes': [{'get': 'node'}, {'get': 'nodes'}],
        'sql': [{'get': 'sql'}],
        'msql': [{'get': 'msql'}, {'get': 'msql'}],
        'dependency': [{'get': 'dependencies'}],
        'dependent': [{'get': 'dependents'}],
        'children': [{'get': 'children'}],
        'module.js': [{}, {}, {'get': 'module_js'}],
        'vopts': [{}, {'get': 'voptions'}],
        'variables': [{'get': 'variables'}],
        })

    def validate_request(f):
        @wraps(f)
        def wrap(self, **kwargs):

            data = None
            if request.data:
                data = json.loads(request.data)
            else:
                data = dict()
                req = request.args or request.form

                for key in req:

                    val = req[key]
                    if key in [
                            u'rolcanlogin', u'rolsuper', u'rolcreatedb',
                            u'rolcreaterole', u'rolinherit', u'rolreplication',
                            u'rolcatupdate', u'variables', u'rolmembership',
                            u'seclabels'
                            ]:
                        data[key] = json.loads(val)
                    else:
                        data[key] = val

            if u'rid' not in kwargs or kwargs['rid'] == -1:
                if u'rolname' not in data:
                    return precondition_required(
                            _("Name is not provided!")
                            )

            if u'rolconnlimit' in data:
                if data[u'rolconnlimit'] is not None:
                    data[u'rolconnlimit'] = int(data[u'rolconnlimit'])
                    if type(data[u'rolconnlimit']) != int or data[u'rolconnlimit'] < -1:
                        return precondition_required(
                                _("Connection limit must be an integer value or equals to -1!")
                                )

            if u'rolmembership' in data:
                if u'rid' not in kwargs or kwargs['rid'] == -1:
                    msg = _("""
Role membership information must be passed as an array of JSON object in the
following format:

rolmembership:[{
    role: [rolename],
    admin: True/False
    },
    ...
]""")
                    if type(data[u'rolmembership']) != list:
                        return precondition_required(msg)

                    data[u'members'] = []
                    data[u'admins'] = []

                    for r in data[u'rolmembership']:
                        if type(r) != dict or u'role' not in r or u'admin' not in r:
                            return precondition_required(msg)
                        else:
                            if r[u'admin']:
                                data[u'admins'].append(r[u'role'])
                            else:
                                data[u'members'].append(r[u'role'])
                else:
                    msg = _("""
Role membership information must be passed a string representing an array of
JSON object in the following format:
rolmembership:{
    'added': [{
        role: [rolename],
        admin: True/False
        },
        ...
        ],
    'deleted': [{
        role: [rolename],
        admin: True/False
        },
        ...
        ],
    'updated': [{
        role: [rolename],
        admin: True/False
        },
        ...
        ]
""")
                    if type(data[u'rolmembership']) != dict:
                        return precondition_required(msg)

                    data[u'members'] = []
                    data[u'admins'] = []
                    data[u'revoked_admins'] = []
                    data[u'revoked'] = []

                    if u'added' in data[u'rolmembership']:
                        roles = (data[u'rolmembership'])[u'added']

                        if type(roles) != list:
                            return precondition_required(msg)

                        for r in roles:
                            if (type(r) != dict or u'role' not in r or
                                    u'admin' not in r):
                                return precondition_required(msg)

                            if r[u'admin']:
                                data[u'admins'].append(r[u'role'])
                            else:
                                data[u'members'].append(r[u'role'])

                    if u'deleted' in data[u'rolmembership']:
                        roles = (data[u'rolmembership'])[u'deleted']

                        if type(roles) != list:
                            return precondition_required(msg)

                        for r in roles:
                            if type(r) != dict or u'role' not in r:
                                return precondition_required(msg)

                            data[u'revoked'].append(r[u'role'])

                    if u'changed' in  data[u'rolmembership']:
                        roles = (data[u'rolmembership'])[u'changed']

                        if type(roles) != list:
                            return precondition_required(msg)

                        for r in roles:
                            if (type(r) != dict or u'role' not in r or
                                    u'admin' not in r):
                                return precondition_required(msg)

                            if not r[u'admin']:
                                data[u'revoked_admins'].append(r[u'role'])
                            else:
                                data[u'admins'].append(r[u'role'])

            if self.manager.version >= 90200:
                if u'seclabels' in data:
                    if u'rid' not in kwargs or kwargs['rid'] == -1:
                        msg = _("""
Security Label must be passed as an array of JSON object in the following
format:
seclabels:[{
    provider: <provider>,
    label: <label>
    },
    ...
]""")
                        if type(data[u'seclabels']) != list:
                            return precondition_required(msg)

                        for s in data[u'seclabels']:
                            if (type(s) != dict or u'provider' not in s or
                                u'label' not in s):
                                return precondition_required(msg)
                    else:
                        msg = _("""
Security Label must be passed as an array of JSON object in the following
format:
seclabels:{
    'added': [{
        provider: <provider>,
        label: <label>
        },
        ...
        ],
    'deleted': [{
        provider: <provider>,
        label: <label>
        },
        ...
        ],
    'updated': [{
        provider: <provider>,
        label: <label>
        },
        ...
        ]
""")
                        seclabels = data[u'seclabels']
                        if type(seclabels) != dict:
                            return precondition_required(msg)

                        if u'added' in seclabels:
                            new_seclabels = seclabels[u'added']


                            if type(new_seclabels) != list:
                                return precondition_required(msg)

                            for s in new_seclabels:
                                if (type(s) != dict or u'provider' not in s or
                                        u'label' not in s):
                                    return precondition_required(msg)

                        if u'deleted' in seclabels:
                            removed_seclabels = seclabels[u'deleted']

                            if type(removed_seclabels) != list:
                                return precondition_required(msg)

                            for s in removed_seclabels:
                                if (type(s) != dict or u'provider' not in s):
                                    return precondition_required(msg)

                        if u'changed' in seclabels:
                            changed_seclabels = seclabels[u'deleted']

                            if type(changed_seclabels) != list:
                                return precondition_required(msg)

                            for s in changed_seclabels:
                                if (type(s) != dict or u'provider' not in s
                                        and u'label' not in s):
                                    return precondition_required(msg)

            if u'variables' in data:
                if u'rid' not in kwargs or kwargs['rid'] == -1:
                    msg = _("""
Configuration parameters/variables must be passed as an array of JSON object in
the following format (create mode):
variables:[{
    database: <database> or null,
    name: <configuration>,
    value: <value>
    },
    ...
]""")
                    if type(data[u'variables']) != list:
                        return precondition_required(msg)

                    for r in data[u'variables']:
                        if (type(r) != dict or
                                u'name' not in r or
                                u'value' not in r):
                            return precondition_required(msg)
                else:
                    msg = _("""
Configuration parameters/variables must be passed as an array of JSON object in
the following format (update mode):
rolmembership:{
    'added': [{
        database: <database> or null,
        name: <configuration>,
        value: <value>
        },
        ...
        ],
    'deleted': [{
        database: <database> or null,
        name: <configuration>,
        value: <value>
        },
        ...
        ],
    'updated': [{
        database: <database> or null,
        name: <configuration>,
        value: <value>
        },
        ...
        ]
""")
                    variables = data[u'variables']
                    if type(variables) != dict:
                        return precondition_required(msg)

                    if u'added' in variables:
                        new_vars = variables[u'added']

                        if type(new_vars) != list:
                            return precondition_required(msg)

                        for v in new_vars:
                            if (type(v) != dict or u'name' not in v or
                                    u'value' not in v):
                                return precondition_required(msg)

                    if u'deleted' in variables:
                        delete_vars = variables[u'deleted']

                        if type(delete_vars) != list:
                            return precondition_required(msg)

                        for v in delete_vars:
                            if type(v) != dict or u'name' not in v:
                                return precondition_required(msg)

                    if u'changed' in  variables:
                        new_vars = variables[u'changed']

                        if type(new_vars) != list:
                            return precondition_required(msg)

                        for v in new_vars:
                            if (type(v) != dict or u'name' not in v or
                                    u'value' not in v):
                                return precondition_required(msg)

            self.request = data

            return f(self, **kwargs)
        return wrap

    def check_precondition(action=None):
        """
        This function will behave as a decorator which will checks the status
        of the database connection for the maintainance database of the server,
        beforeexecuting rest of the operation for the wrapped function. It will
        also attach manager, conn (maintenance connection for the server) as
        properties of the instance.
        """
        def wrap(f):
            @wraps(f)
            def wrapped(self, **kwargs):
                self.manager = get_driver(
                        PG_DEFAULT_DRIVER
                        ).connection_manager(
                                kwargs['sid']
                                )
                self.conn = self.manager.connection()

                if not self.conn.connected():
                    return precondition_required(
                            _("Connection to the server has been lost!")
                            )

                ver = self.manager.version

                self.sql_path = 'role/sql/{0}/'.format(
                    'post9_4' if ver >= 90500 else \
                    'post9_1' if ver >= 90200 else \
                    'post9_0' if ver >= 90100 else \
                    'post8_4'
                    )

                self.alterKeys = [
                        u'rolcanlogin', u'rolsuper', u'rolcreatedb',
                        u'rolcreaterole', u'rolinherit', u'rolreplication',
                        u'rolconnlimit', u'rolvaliduntil', u'rolpassword'
                        ] if ver >= 90200 else [
                                u'rolcanlogin', u'rolsuper', u'rolcreatedb',
                                u'rolcreaterole', u'rolinherit', u'rolconnlimit',
                                u'rolvaliduntil', u'rolpassword'
                                ]

                auth_tbl=False
                check_permission=False
                fetch_name=False
                forbidden_msg = None

                if action in ['list', 'properties']:
                    auth_tbl = True
                elif action in ['drop', 'update']:
                    check_permission = True
                    fetch_name = True
                    if action == 'drop':
                        forbidden_msg = _(
                                "The current user does not have permission to drop the role!"
                                )
                    else:
                        forbidden_msg = _(
                                "The current user does not have permission to update the role!"
                                )
                elif action == 'create':
                    check_permission = True
                    forbidden_msg = _(
                            "The current user does not have permission to create the role!"
                            )
                elif (action == 'msql' and
                        'rid' in kwargs and kwargs['rid'] != -1):
                    fetch_name = True

                if auth_tbl:
                    status, res = self.conn.execute_scalar(
                        "SELECT has_table_privilege('pg_authid', 'SELECT')"
                        )

                    if not status:
                        return internal_server_error(
                                _(
                                    "Error checking the permission to the pg_authid!\n{0}"
                                    ).format(res)
                                )
                    self.role_tbl = 'pg_authid' if res else 'pg_roles'
                else:
                    self.role_tbl = 'pg_roles'

                if check_permission:
                    user = self.manager.user_info

                    if not user['is_superuser'] and not user['can_create_role']:
                        if (action != 'update' or
                                'rid' in kwargs and kwargs['rid'] != -1 and
                                user['id'] != rid):
                            return forbidden(forbidden_msg)

                if fetch_name:

                    status, res = self.conn.execute_dict(
                       render_template(
                           self.sql_path + 'permission.sql',
                           rid=kwargs['rid'],
                           conn=self.conn
                           )
                       )

                    if not status:
                        return internal_server_error(
                                _(
                                    "ERROR: fetching the role information!\n{0}"
                                    ).format(res)
                                )

                    if len(res['rows']) == 0:
                        return gone(
                                _("Couldn't find the specific role in the database server!")
                                )

                    row = res['rows'][0]

                    self.role = row['rolname']
                    self.rolCanLogin = row['rolcanlogin']
                    self.rolCatUpdate = row['rolcatupdate']
                    self.rolSuper = row['rolsuper']

                return f(self, **kwargs)
            return wrapped
        return wrap

    @check_precondition(action='list')
    def list(self, gid, sid):
        status, res = self.conn.execute_dict(
                render_template(self.sql_path + 'properties.sql',
                    role_tbl=self.role_tbl
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the roles from the database server!\n{0}"
                        ).format(res)
                    )

        self.transform(res)

        return ajax_response(
                response=res['rows'],
                status=200
                )

    @check_precondition(action='nodes')
    def nodes(self, gid, sid):

        status, rset = self.conn.execute_2darray(
                render_template(self.sql_path + 'nodes.sql',
                    role_tbl=self.role_tbl
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the roles information from the database server!\n{0}"
                        ).format(res)
                    )

        res = []
        for row in rset['rows']:
            res.append(
                    self.blueprint.generate_browser_node(
                        row['oid'], sid,
                        row['rolname'],
                        'icon-role' if row['rolcanlogin'] else 'icon-group',
                        can_login=row['rolcanlogin'],
                        is_superuser=row['rolsuper']
                        )
                    )

        return make_json_response(
                data=res,
                status=200
                )

    @check_precondition(action='node')
    def node(self, gid, sid, rid):

        status, rset = self.conn.execute_2darray(
                render_template(self.sql_path + 'nodes.sql',
                    rid=rid,
                    role_tbl=self.role_tbl
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the roles information from the database server!\n{0}"
                        ).format(res)
                    )

        for row in rset['rows']:
            return make_json_response(
                    data=self.blueprint.generate_browser_node(
                        row['oid'], sid,
                        row['rolname'],
                        'icon-role' if row['rolcanlogin'] else 'icon-group',
                        can_login=row['rolcanlogin'],
                        is_superuser=row['rolsuper']
                        ),
                    status=200
                    )

        return gone(_("Couldn't find the role information!"))

    def transform(self, rset):
        for row in rset['rows']:
            res = []
            roles = row['rolmembership']
            row['rolpassword'] = ''
            for role in roles:
                role = re.search(r'([01])(.+)', role)
                res.append({
                    'role': role.group(2),
                    'admin': True if role.group(1) == '1' else False
                    })
            row['rolmembership'] = res
            row['rolvaliduntil'] = row['rolvaliduntil'].isoformat() \
                    if isinstance(
                            row['rolvaliduntil'],
                            (datetime.date, datetime.datetime)
                            ) else None
            if 'seclabels' in row and row['seclabels'] is not None:
                res = []
                for sec in row['seclabels']:
                    sec = re.search(r'([^=]+)=(.*$)', sec)
                    res.append({
                        'provider': sec.group(1),
                        'label': sec.group(2)
                        })

    @check_precondition(action='properties')
    def properties(self, gid, sid, rid):

        status, res = self.conn.execute_dict(
                render_template(self.sql_path + 'properties.sql',
                    role_tbl=self.role_tbl,
                    rid=rid
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the roles from the database server!\n{0}"
                        ).format(res)
                    )

        self.transform(res)
        if len(res['rows']) == 0:
            return gone(_("Couldn't find the role information!"))

        return ajax_response(
                response=res['rows'][0],
                status=200
                )

    @check_precondition(action='drop')
    def drop(self, gid, sid, rid):

        status, res = self.conn.execute_2darray(
                "DROP ROLE {0};".format(self.role)
                )
        if not status:
            return internal_server_error(
                    _("ERROR: Couldn't drop the user!\n{0}").format(res)
                    )

        return success_return()

    @check_precondition()
    def sql(self, gid, sid, rid):
        status, res = self.conn.execute_scalar(
                render_template(
                    self.sql_path + 'sql.sql',
                    role_tbl=self.role_tbl
                    ),
                dict({'rid':rid})
                )

        if not status:
            return internal_server_error(
                    _("ERROR: Couldn't generate reversed engineered Query for the role/user!\n{0}").format(
                        res
                        )
                    )

        if res is None:
            return gone(
                    _("ERROR: Couldn't generate reversed engineered Query for the role/user!")
                    )

        return ajax_response(response=res)

    @check_precondition(action='create')
    @validate_request
    def create(self, gid, sid):

        sql = render_template(
                self.sql_path + 'create.sql',
                data=self.request,
                dummy=False,
                conn=self.conn
                )

        status, msg = self.conn.execute_dict(sql)

        if not status:
            return internal_server_error(
                    _("ERROR: Couldn't create the role!\n{0}").format(msg)
                    )

        status, rid = self.conn.execute_scalar(
                "SELECT oid FROM {0} WHERE rolname = %(rolname)s".format(
                    self.role_tbl
                    ),
                {'rolname': self.request[u'rolname']}
                )

        if not status:
            return internal_server_error(
                    _("ERROR: Couldn't fetch the role information!\n{0}").format(msg)
                    )


        status, rset = self.conn.execute_dict(
                render_template(self.sql_path + 'nodes.sql',
                    rid=rid,
                    role_tbl=self.role_tbl
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the roles information from the database server!\n{0}"
                        ).format(res)
                    )
        for row in rset['rows']:
            return jsonify(
                    node=self.blueprint.generate_browser_node(
                        rid, sid,
                        row['rolname'],
                        'icon-role' if row['rolcanlogin'] else 'icon-group',
                        can_login=row['rolcanlogin']
                        )
                    )

        return gone(_("Couldn't find the role information!"))

    @check_precondition(action='update')
    @validate_request
    def update(self, gid, sid, rid):

        sql = render_template(
                self.sql_path + 'update.sql',
                data=self.request,
                dummy=False,
                conn=self.conn,
                role=self.role,
                rolCanLogin=self.rolCanLogin,
                rolCatUpdate=self.rolCatUpdate,
                rolSuper=self.rolSuper,
                alterKeys=self.alterKeys
                )

        status, msg = self.conn.execute_dict(sql)

        if not status:
            return internal_server_error(
                    _("ERROR: Couldn't create the role!\n{0}").format(msg)
                    )

        status, rset = self.conn.execute_dict(
                render_template(self.sql_path + 'nodes.sql',
                    rid=rid,
                    role_tbl=self.role_tbl
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the roles information from the database server!\n{0}"
                        ).format(res)
                    )

        for row in rset['rows']:
            return jsonify(
                    node=self.blueprint.generate_browser_node(
                        rid, sid,
                        row['rolname'],
                        'icon-role' if row['rolcanlogin'] else 'icon-group',
                        can_login=row['rolcanlogin'],
                        is_superuser=row['rolsuper']
                        )
                    )

        return gone(_("Couldn't find the role information!"))

    @check_precondition(action='msql')
    @validate_request
    def msql(self, gid, sid, rid=-1):
        if rid == -1:
            return make_json_response(
                    data=render_template(
                        self.sql_path + 'create.sql',
                        data=self.request,
                        dummy=True,
                        conn=self.conn
                        )
                    )
        else:
            return make_json_response(
                    data=render_template(
                        self.sql_path + 'update.sql',
                        data=self.request,
                        dummy=True,
                        conn=self.conn,
                        role=self.role,
                        rolCanLogin=self.rolCanLogin,
                        rolCatUpdate=self.rolCatUpdate,
                        rolSuper=self.rolSuper,
                        alterKeys=self.alterKeys
                        )
                    )

    @check_precondition()
    def dependencies(self, gid, sid, rid):
        return not_implemented()

    @check_precondition()
    def dependents(self, gid, sid, rid):
        return not_implemented()

    @check_precondition()
    def variables(self, gid, sid, rid):

        status, rset = self.conn.execute_dict(
                render_template(self.sql_path + 'variables.sql',
                    rid=rid
                    )
                )

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the variable information for the given role!\n{0}"
                        ).format(rset)
                    )

        return make_json_response(
                data=rset['rows']
                )

    @check_precondition()
    def voptions(self, gid, sid):

        status, res = self.conn.execute_dict(
                """
SELECT
	name, vartype, min_val, max_val, enumvals
FROM
    (
	SELECT
		'role'::text AS name, 'string'::text AS vartype,
		NULL AS min_val, NULL AS max_val, NULL::text[] AS enumvals
	UNION ALL
	SELECT
		name, vartype, min_val::numeric AS min_val, max_val::numeric AS max_val, enumvals
	FROM
		pg_settings
	WHERE
		context in ('user', 'superuser')
	) a""")

        if not status:
            return internal_server_error(
                    _(
                        "Error fetching the variable options for role!\n{0}"
                        ).format(res)
                    )
        return make_json_response(
                data=res['rows']
                )


RoleView.register_node_view(blueprint)
