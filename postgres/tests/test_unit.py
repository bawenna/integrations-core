# (C) Datadog, Inc. 2018-present
# All rights reserved
# Licensed under Simplified BSD License (see LICENSE)
import mock
import psycopg2
import pytest
from mock import MagicMock
from pytest import fail
from semver import VersionInfo
from six import iteritems

from datadog_checks.postgres import statements, util

from .common import SCHEMA_NAME

pytestmark = pytest.mark.unit


def test_get_instance_metrics_lt_92(integration_check, pg_instance):
    """
    check output when 9.2+
    """
    pg_instance['collect_database_size_metrics'] = False
    check = integration_check(pg_instance)

    res = check.metrics_cache.get_instance_metrics(VersionInfo(9, 1, 0))
    assert res['metrics'] == util.COMMON_METRICS


def test_get_instance_metrics_92(integration_check, pg_instance):
    """
    check output when <9.2
    """
    pg_instance['collect_database_size_metrics'] = False
    check = integration_check(pg_instance)

    res = check.metrics_cache.get_instance_metrics(VersionInfo(9, 2, 0))
    assert res['metrics'] == dict(util.COMMON_METRICS, **util.NEWER_92_METRICS)


def test_get_instance_metrics_state(integration_check, pg_instance):
    """
    Ensure data is consistent when the function is called more than once
    """
    pg_instance['collect_database_size_metrics'] = False
    check = integration_check(pg_instance)

    res = check.metrics_cache.get_instance_metrics(VersionInfo(9, 2, 0))
    assert res['metrics'] == dict(util.COMMON_METRICS, **util.NEWER_92_METRICS)

    res = check.metrics_cache.get_instance_metrics('foo')  # metrics were cached so this shouldn't be called
    assert res['metrics'] == dict(util.COMMON_METRICS, **util.NEWER_92_METRICS)


def test_get_instance_metrics_database_size_metrics(integration_check, pg_instance):
    """
    Test the function behaves correctly when `database_size_metrics` is passed
    """
    pg_instance['collect_default_database'] = True
    pg_instance['collect_database_size_metrics'] = False
    check = integration_check(pg_instance)

    expected = util.COMMON_METRICS
    expected.update(util.NEWER_92_METRICS)
    expected.update(util.DATABASE_SIZE_METRICS)
    res = check.metrics_cache.get_instance_metrics(VersionInfo(9, 2, 0))
    assert res['metrics'] == expected


def test_get_instance_with_default(check):
    """
    Test the contents of the query string with different `collect_default_db` values
    """
    version = VersionInfo(9, 2, 0)
    res = check.metrics_cache.get_instance_metrics(version)
    assert "  AND psd.datname not ilike 'postgres'" in res['query']

    check.config.collect_default_db = True
    res = check.metrics_cache.get_instance_metrics(version)
    assert "  AND psd.datname not ilike 'postgres'" not in res['query']


def test_malformed_get_custom_queries(check):
    """
    Test early-exit conditions for _get_custom_queries()
    """
    check.log = MagicMock()
    db = MagicMock()
    check.db = db

    check.config.custom_queries = [{}]

    # Make sure 'metric_prefix' is defined
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with("custom query field `metric_prefix` is required")
    check.log.reset_mock()

    # Make sure 'query' is defined
    malformed_custom_query = {'metric_prefix': 'postgresql'}
    check.config.custom_queries = [malformed_custom_query]

    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "custom query field `query` is required for metric_prefix `%s`", malformed_custom_query['metric_prefix']
    )
    check.log.reset_mock()

    # Make sure 'columns' is defined
    malformed_custom_query['query'] = 'SELECT num FROM sometable'
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "custom query field `columns` is required for metric_prefix `%s`", malformed_custom_query['metric_prefix']
    )
    check.log.reset_mock()

    # Make sure we gracefully handle an error while performing custom queries
    malformed_custom_query_column = {}
    malformed_custom_query['columns'] = [malformed_custom_query_column]
    db.cursor().execute.side_effect = psycopg2.ProgrammingError('FOO')
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "Error executing query for metric_prefix %s: %s", malformed_custom_query['metric_prefix'], 'FOO'
    )
    check.log.reset_mock()

    # Make sure the number of columns defined is the same as the number of columns return by the query
    malformed_custom_query_column = {}
    malformed_custom_query['columns'] = [malformed_custom_query_column]
    query_return = ['num', 1337]
    db.cursor().execute.side_effect = None
    db.cursor().__iter__.return_value = iter([query_return])
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "query result for metric_prefix %s: expected %s columns, got %s",
        malformed_custom_query['metric_prefix'],
        len(malformed_custom_query['columns']),
        len(query_return),
    )
    check.log.reset_mock()

    # Make sure the query does not return an empty result
    db.cursor().__iter__.return_value = iter([[]])
    check._collect_custom_queries([])
    check.log.debug.assert_called_with(
        "query result for metric_prefix %s: returned an empty result", malformed_custom_query['metric_prefix']
    )
    check.log.reset_mock()

    # Make sure 'name' is defined in each column
    malformed_custom_query_column['some_key'] = 'some value'
    db.cursor().__iter__.return_value = iter([[1337]])
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "column field `name` is required for metric_prefix `%s`", malformed_custom_query['metric_prefix']
    )
    check.log.reset_mock()

    # Make sure 'type' is defined in each column
    malformed_custom_query_column['name'] = 'num'
    db.cursor().__iter__.return_value = iter([[1337]])
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "column field `type` is required for column `%s` of metric_prefix `%s`",
        malformed_custom_query_column['name'],
        malformed_custom_query['metric_prefix'],
    )
    check.log.reset_mock()

    # Make sure 'type' is a valid metric type
    malformed_custom_query_column['type'] = 'invalid_type'
    db.cursor().__iter__.return_value = iter([[1337]])
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "invalid submission method `%s` for column `%s` of metric_prefix `%s`",
        malformed_custom_query_column['type'],
        malformed_custom_query_column['name'],
        malformed_custom_query['metric_prefix'],
    )
    check.log.reset_mock()

    # Make sure we're only collecting numeric value metrics
    malformed_custom_query_column['type'] = 'gauge'
    query_return = MagicMock()
    query_return.__float__.side_effect = ValueError('Mocked exception')
    db.cursor().__iter__.return_value = iter([[query_return]])
    check._collect_custom_queries([])
    check.log.error.assert_called_once_with(
        "non-numeric value `%s` for metric column `%s` of metric_prefix `%s`",
        query_return,
        malformed_custom_query_column['name'],
        malformed_custom_query['metric_prefix'],
    )


@pytest.mark.parametrize(
    'test_case, params',
    [
        ('9.6.2', {'version.major': '9', 'version.minor': '6', 'version.patch': '2'}),
        ('10.0', {'version.major': '10', 'version.minor': '0', 'version.patch': '0'}),
        (
            '11nightly3',
            {'version.major': '11', 'version.minor': '0', 'version.patch': '0', 'version.release': 'nightly.3'},
        ),
    ],
)
def test_version_metadata(check, test_case, params):
    check.check_id = 'test:123'
    with mock.patch('datadog_checks.base.stubs.datadog_agent.set_check_metadata') as m:
        check.set_metadata('version', test_case)
        for name, value in iteritems(params):
            m.assert_any_call('test:123', name, value)
        m.assert_any_call('test:123', 'version.scheme', 'semver')
        m.assert_any_call('test:123', 'version.raw', test_case)


@pytest.mark.usefixtures('mock_cursor_for_replica_stats')
def test_replication_stats(aggregator, integration_check, pg_instance):
    check = integration_check(pg_instance)
    check.check(pg_instance)
    base_tags = ['foo:bar', 'server:localhost', 'port:5432']
    app1_tags = base_tags + ['wal_sync_state:async', 'wal_state:streaming', 'wal_app_name:app1']
    app2_tags = base_tags + ['wal_sync_state:sync', 'wal_state:backup', 'wal_app_name:app2']

    aggregator.assert_metric('postgresql.db.count', 0, base_tags)
    for suffix in ('wal_write_lag', 'wal_flush_lag', 'wal_replay_lag'):
        metric_name = 'postgresql.replication.{}'.format(suffix)
        aggregator.assert_metric(metric_name, 12, app1_tags)
        aggregator.assert_metric(metric_name, 13, app2_tags)

    aggregator.assert_all_metrics_covered()


def test_relation_filter():
    relations_config = {'breed': {'relation_name': 'breed', 'schemas': ['public']}}
    query_filter = util.build_relations_filter(relations_config, SCHEMA_NAME)
    assert query_filter == "( relname = 'breed' AND schemaname = ANY(array['public']::text[]) )"


def test_relation_filter_no_schemas():
    relations_config = {'persons': {'relation_name': 'persons', 'schemas': [util.ALL_SCHEMAS]}}
    query_filter = util.build_relations_filter(relations_config, SCHEMA_NAME)
    assert query_filter == "( relname = 'persons' )"


def test_relation_filter_regex():
    relations_config = {'persons': {'relation_regex': 'b.*', 'schemas': [util.ALL_SCHEMAS]}}
    query_filter = util.build_relations_filter(relations_config, SCHEMA_NAME)
    assert query_filter == "( relname ~ 'b.*' )"


def test_query_timeout_connection_string(aggregator, integration_check, pg_instance):
    pg_instance['password'] = ''
    pg_instance['query_timeout'] = 1000

    check = integration_check(pg_instance)
    try:
        check._connect()
    except psycopg2.ProgrammingError as e:
        fail(str(e))
    except psycopg2.OperationalError:
        # could not connect to server because there is no server running
        pass


def test_generate_synthetic_rows():
    rows = [
        {
            'calls': 45,
            'total_time': 1134,
            'rows': 800,
            'shared_blks_hit': 15,
            'shared_blks_read': 5,
            'shared_blks_dirtied': 10,
            'shared_blks_written': 10,
            'local_blks_hit': 10,
            'local_blks_read': 10,
            'local_blks_dirtied': 10,
            'local_blks_written': 10,
            'temp_blks_read': 10,
            'temp_blks_written': 10,
        },
        {
            'calls': 0,
            'total_time': 0,
            'rows': 0,
            'shared_blks_hit': 0,
            'shared_blks_read': 0,
            'shared_blks_dirtied': 0,
            'shared_blks_written': 0,
            'local_blks_hit': 0,
            'local_blks_read': 0,
            'local_blks_dirtied': 0,
            'local_blks_written': 0,
            'temp_blks_read': 0,
            'temp_blks_written': 10,
        },
    ]
    result = statements.generate_synthetic_rows(rows)
    assert result == [
        {
            'avg_time': 25.2,
            'calls': 45,
            'total_time': 1134,
            'rows': 800,
            'shared_blks_ratio': 0.75,
            'shared_blks_hit': 15,
            'shared_blks_read': 5,
            'shared_blks_dirtied': 10,
            'shared_blks_written': 10,
            'local_blks_hit': 10,
            'local_blks_read': 10,
            'local_blks_dirtied': 10,
            'local_blks_written': 10,
            'temp_blks_read': 10,
            'temp_blks_written': 10,
        },
        {
            'avg_time': 0,
            'calls': 0,
            'total_time': 0,
            'rows': 0,
            'shared_blks_ratio': 0,
            'shared_blks_hit': 0,
            'shared_blks_read': 0,
            'shared_blks_dirtied': 0,
            'shared_blks_written': 0,
            'local_blks_hit': 0,
            'local_blks_read': 0,
            'local_blks_dirtied': 0,
            'local_blks_written': 0,
            'temp_blks_read': 0,
            'temp_blks_written': 10,
        },
    ]
