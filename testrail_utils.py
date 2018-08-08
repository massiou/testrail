#!/usr/bin/env python
# coding: utf-8

"""
Testrail utilities
"""

import json
import logging
import os
import tempfile
import time

import requests

LOG_FILE = '{0}.log'.format(tempfile.NamedTemporaryFile().name)
FORMAT = '[%(asctime)s] %(message)s'

# Create logger
logging.basicConfig(level=logging.INFO, format=FORMAT)

# Add FileHandler and only log WARNING and higher
file_h = logging.FileHandler(LOG_FILE)
file_h.name = 'File Logger'
file_h.level = logging.DEBUG
file_h.formatter = logging.Formatter(FORMAT)

log = logging.getLogger(__name__)
log.addHandler(file_h)

URL_ARTIFACTS_PUBLIC = (
    'https://eve.devsca.com/bitbucket/scality/ring/artifacts/builds/'
)
URL_BASE = 'https://scality.testrail.net/'


try:
    ART_LOGIN = os.environ['ARTIFACTS_LOGIN']
    ART_PWD = os.environ['ARTIFACTS_PWD']
    ARTIFACTS_CRED = '{0}:{1}'.format(ART_LOGIN, ART_PWD)
except KeyError:
    log.info('ARTIFACTS_LOGIN and/or ARTIFACTS_PWD not found')
    ARTIFACTS_CRED = None

if ARTIFACTS_CRED:
    URL_ARTIFACTS_OLD = (
        "https://{0}@artifacts.devsca.com/builds/".format(
            ARTIFACTS_CRED)
    )
    URL_ARTIFACTS_OLD_WO_CREDS = "https://artifacts.devsca.com/builds/"

    URL_ARTIFACTS = (
        "https://{0}@eve.devsca.com/bitbucket/scality/ring/artifacts/builds/".format(
            ARTIFACTS_CRED)
    )
    URL_ARTIFACTS_WO_CREDS = (
        "https://eve.devsca.com/bitbucket/scality/ring/artifacts/builds/"
    )

#TODO Use only one ARTIFACT_URL*, the one provided by artifacts_private_url
# Following sections to be removed
else:
    URL_ARTIFACTS_OLD = URL_ARTIFACTS_OLD_WO_CREDS = (
        "http://artifacts/builds/"
    )
    URL_ARTIFACTS = URL_ARTIFACTS_WO_CREDS = (
        "http://artifacts/builds/"
    )

HEADER = {"Content-Type": "application/json"}
RING_ID = 1

try:
    LOGIN = os.environ['TESTRAIL_LOGIN']
except KeyError:
    raise Exception('Please export TESTRAIL_LOGIN environment variable')

try:
    KEY = os.environ['TESTRAIL_KEY']
except KeyError:
    raise Exception('Please export TESTRAIL_KEY environment variable')


def testrail_get(cmd, t_id, **params):
    """
    Process cmd through testrail API v2

    example: cmd="get_suites"

    :param cmd: get command to perform
    :type cmd: string
    :param t_id: testrail project or suite id
    :type t_id: integer
    :param params: url parameters (example: testsuite=1)
    :type params: dict
    :return: ret
    :rtype: dict
    """
    url_params = "&".join([str(t_id)] + ["{0}={1}".format(k, v)
                                         for k, v in params.items()
                                         if v is not None])

    url = os.path.join(URL_BASE, "index.php?/api/v2/{0}/{1}".format(
        cmd, url_params))

    log.info(url)
    req = requests.get(url, headers=HEADER, auth=(LOGIN, KEY))
    ret = req.json()

    return ret


def testrail_post(url, request, session=None):
    """

    :param url: tesrail URL
    :type url: string
    :param request: payload
    :type: dict
    :param session: requests session
    :type session: `requests.Session`
    :return:
    """
    if session:
        ret = session.post(url,
                        headers=HEADER,
                        data=json.dumps(request),
                        auth=(LOGIN, KEY))
    else:
        ret = requests.post(url,
                        headers=HEADER,
                        data=json.dumps(request),
                        auth=(LOGIN, KEY))

    status_code = ret.status_code
    if status_code != 200:
        log.info('status code: %s, log: %s, reason: %s',
                 status_code, ret.text, ret.reason)

    return ret


def add_plan(name, milestone, description):
    """

    :param name: testrail plan name
    :type name: string
    :param milestone (optional): testrail milestone linked to the test plan
    :type milestone: string
    :param description:
    :type description: string
    :return: None
    """

    url = os.path.join(URL_BASE, 'index.php?/api/v2/add_plan/{0}'.format(
        RING_ID
    ))
    log.info("Add plan %s", name)
    request = {"name": name, "suite_id": 1, "description": description}
    if milestone:
        milestone_id = get_milestone(milestone)
        request['milestone_id'] = milestone_id
    ret = testrail_post(url, request)

    return ret


def add_plan_entry(plan_id, suite_id, config_ids, centos_tests):
    """
    Add suite and config to an existing testrail plan

    :param plan_id: testrail plan
    :type plan_id: integer
    :param suite_id: testrail tests suite
    :type suite_id: integer
    :param config_ids: testrail list of configuration (related to tests suite)
    :type config_ids: list of integers
    :return: None
    """
    url = os.path.join(URL_BASE, 'index.php?/api/v2/add_plan_entry/{0}'.format(
        plan_id
    ))

    runs_list = [
        {
            "include_all": False,
            "case_ids": centos_tests,
            "config_ids": [1, ]
        },
        {
            "include_all": False,
            "case_ids": centos_tests,
            "config_ids": [2, ]
        },
        {
            "include_all": True,
            "config_ids": [3, ]
        }

    ]

    request = {
        "suite_id": suite_id,
        "config_ids": config_ids,
        "runs": runs_list
    }

    ret = testrail_post(url, request)
    return ret


def add_testcase(test_case, section_id, testrail_cases_name):
    """
    Add a single test case to a section in a test suite

    :param test_case: name of the test case
    :type test_case: string
    :param section_id: testsuite section ('fuse' for example)
    :type section_id: integer
    :param testrail_cases_name: list of test cases already in testrail testsuite
    :type testrail_cases_name: list of string
    :return:
    """
    url = os.path.join(URL_BASE, "index.php?/api/v2/add_case/{0}".format(
        section_id))
    log.debug('Add case: %s', url)

    request = {"title": test_case}

    log.info('test case: %s', test_case)
    log.debug(json.dumps(request))

    # Avoid doublon
    if test_case in testrail_cases_name:
        log.warning('test case already exists: %s', test_case)
        return

    log.info(url)

    # Handle `Too many requests error`
    status_code = 429
    while status_code == 429:
        ret = testrail_post(url, request)
        status_code = ret.status_code

    return status_code


def update_plan_entry(plan_id, entry_id, description):
    """
    Update test runs of a test plan to include all new added testcases

    :param plan_id: testrail plan
    :type plan_id: integer
    :param entry_id: testrail run entry_id
    :type entry_id: integer
    :param description: desc of the test plan
    :type description: string
    :return: None
    """
    log.info(description)
    url = os.path.join(
        URL_BASE, 'index.php?/api/v2/update_plan_entry/{0}/{1}'.format(
            plan_id, entry_id
        ))
    request = {
        "include_all": True,
        "description": description
    }

    ret = testrail_post(url, request)
    return ret


def add_sections(suite, sections):
    """
    Add sections to a testrail testsuite
    :param sections: testrail sections
    :type sections: list of string
    :return:
    """
    suite_id = get_suite(suite)
    for section in sections:
        url = os.path.join(URL_BASE, 'index.php?/api/v2/add_section/1')
        log.info("Add %s section", section)
        request = {"name": section, "suite_id": suite_id}
        ret = testrail_post(url, request)
        assert ret.status_code != 400


def get_open_plans():
    """
    Get all testrail plan not completed

    :return: list of testrail plans
    :rtype: list of dict
    """
    plans = testrail_get("get_plans", RING_ID, is_completed=0)

    return plans


def get_open_plan(version):
    """

    :param version:
    :return:
    """
    plans = get_open_plans()
    for plan in plans:
        name = plan.get('name')
        if name == version:
            log.info("Plan already exists %s", name)
            return plan.get("id")


def get_plans_created_before(timestamp, offset=0):
    """

    :return: list of tuples (plan_id, created_on)
    """
    plans = testrail_get(
        "get_plans", RING_ID, created_before=int(timestamp), offset=offset)
    print plans
    return [(plan.get('name'), plan.get('id'), plan.get('created_on'))
            for plan in plans]


def close_plan(plan_id):
    """
    Close and archive test plan and associated runs

    :param plan_id: testrail run
    :type plan_id: integer
    :return: None
    """
    url = os.path.join(
        URL_BASE, 'index.php?/api/v2/close_plan/{0}'.format(plan_id)
    )

    ret = testrail_post(url, {})
    return ret


def close_plans(pattern):
    """
    Close testrail plans

    :param pattern: test plan pattern name
    :type pattern: string
    :return:
    """
    plans = get_open_plans()
    log.info("%s open plans", len(plans))
    count = 0
    for plan in plans:
        name = plan.get('name')
        if name.startswith(pattern):
            log.info("Closing plan %s", name)
            ret = close_plan(plan.get("id"))
            # Warn current plan has not been closed
            if ret.status_code != 200:
                log.info('status code: %s, log: %s, reason: %s',
                         ret.status_code, ret.text, ret.reason)
            else:
                count += 1
    log.info("%s plan(s) closed with pattern %s", count, pattern)


def delete_plan(plan_id, session=None):
    url = os.path.join(
        URL_BASE, "index.php?/api/v2/delete_plan/{0}".format(plan_id)
    )
    ret = testrail_post(url, {}, session)

    return ret


def get_suite(suite):
    """

    :param suite: testsuite name
    :type suite: string
    :rtype: integer
    """
    suites = testrail_get('get_suites', RING_ID)
    suite_id = [s["id"] for s in suites if s['name'] == suite]

    return suite_id[0]


def get_section(suite_id, section):
    """

    :param suite_id: id of the testsuite
    :type suite_id: integer
    :param section: name of the section
    :type section: string
    :return: section_id
    :rtype: integer
    """
    sections = testrail_get("get_sections", RING_ID, suite_id=suite_id)
    for c_section in sections:
        if c_section['name'] == section:
            return c_section['id']


def get_sections(suite_id):
    """
    Get all sections name

    :param suite_id: id of the testsuite
    :type suite_id: integer
    :return: sections
    :rtype: list of string
    """
    sections = testrail_get("get_sections", RING_ID, suite_id=suite_id)
    return sections


def get_plan(version):
    """
    Get testrail plan related to a version

    :param version:
    :return: plan id
    :rtype: integer
    """
    plans = testrail_get('get_plans', RING_ID)
    log.debug(plans)
    assert plans
    for plan in plans:
        if plan['name'] == version:
            return plan['id']


def get_runs(plan_id):
    """

    :param plan_id:
    :return:
    """

    runs = testrail_get("get_plan", plan_id)
    return runs['entries'][0]['runs']


def get_entries_id(plan_id):
    """

    :param plan_id:
    :return:
    """

    runs = get_runs(plan_id)
    return [(run['entry_id'], run['config']) for run in runs]


def get_run(plan_id, distrib):
    """

    :param plan_id:
    :param distrib:
    :return:
    """
    runs = get_runs(plan_id)
    for run in runs:
        if run['config'].lower() == distrib.lower():
            return run['id']


def get_cases(suite, section=None):
    """

    :param suite: testrail suite
    :type suite: string
    :return:
    """
    suite_id = get_suite(suite)
    if section:
        section_id = get_section(suite_id, section)
    else:
        section_id = None
    return testrail_get("get_cases",
                        RING_ID,
                        suite_id=suite_id,
                        section_id=section_id)


def get_case(name, suite, section=None):
    """

    :param name:
    :param suite:
    :param section:
    :return:
    """

    cases = get_cases(suite, section)

    for case in cases:
        if case.get('title') == name:
            return case.get('id')


def get_milestones(project_id=RING_ID):
    """

    :param project_id:
    :return:
    """
    return testrail_get("get_milestones", project_id)


def get_milestone(name):
    """

    :param name:
    :return:
    """
    milestones = get_milestones()

    for milestone in milestones:
        if milestone.get('name') == name:
            return milestone.get('id')


def get_tests(run_id):
    """

    :param run_id: id of testrail run
    :type run_id: integer
    :return:
    """
    log.info("Get all the tests ids from run %s", run_id)
    return testrail_get("get_tests", run_id)


def get_test(name, run_id):
    """

    :param tests:
    :return:
    """
    tests = get_tests(run_id)

    for test in tests:
        if test.get('title') == name:
            return test.get('id')


def put_results(run, results, tests_db):
    """

    :param run:
    :param: results
    :param tests_db:
    :return:
    """

    log.debug(tests_db)

    results_d = {'results': results}

    number_of_res = len(results)

    # POST results dictionary
    url = URL_BASE + "index.php?/api/v2/add_results/{0}".format(run)
    status_code = 429
    attempts = 0
    while status_code == 429:
        log.info('Posting results...')
        while attempts < 5:
            try:
                ret = testrail_post(url, results_d)
                status_code = ret.status_code
                break
            except Exception as exc:
                log.info(exc)
                attempts += 1
                if attempts >= 5:
                    return 0

    log.info('Nb results: %s', number_of_res)
    return number_of_res
