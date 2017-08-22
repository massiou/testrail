#!/usr/bin/env python
# coding: utf-8

"""
Testrail upload utility
"""

from argparse import ArgumentParser, ArgumentError, RawDescriptionHelpFormatter
from collections import defaultdict, namedtuple
import fnmatch
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from xml.etree.ElementTree import parse

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

ARTIFACTS_CRED = ''
URL_BASE = ''
URL_ARTIFACTS = (
    "https://{0}@".format(
        ARTIFACTS_CRED)
)
HEADER = {"Content-Type": "application/json"}
RING_ID = 1
OS = ('Centos6', 'Centos7', 'Trusty')
SECTIONS = []

NOT_FOUND_FILE = ".tests_not_found_{0}".format(int(time.time()))

try:
    LOGIN = os.environ['TESTRAIL_LOGIN']
except KeyError:
    raise Exception('Please export TESTRAIL_LOGIN environment variable')

try:
    KEY = os.environ['TESTRAIL_KEY']
except KeyError:
    raise Exception('Please export TESTRAIL_KEY environment variable')

RANDOM_TEST_NAMES = {
    '':
        [
        ]
}
report_obj = namedtuple('report', ['path', 'section', 'distrib'])


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
                                         for k, v in params.iteritems()
                                         if v])

    url = os.path.join(URL_BASE, "index.php?/api/v2/{0}/{1}".format(
        cmd, url_params))
    log.info(url)
    req = requests.get(url, headers=HEADER, auth=(LOGIN, KEY))
    ret = req.json()

    return ret


def add_plan(name, milestone=None):
    """

    :param name: testrail plan name
    :type name: string
    :return: None
    """

    url = os.path.join(URL_BASE, 'index.php?/api/v2/add_plan/{0}'.format(
        RING_ID
    ))
    log.info("Add plan %s", name)
    request = {"name": name, "suite_id": 1}
    if milestone:
        milestone_id = get_milestone(milestone)
        request['milestone_id'] = milestone_id
    ret = requests.post(url,
                        headers=HEADER,
                        data=json.dumps(request),
                        auth=(LOGIN, KEY))
    status_code = ret.status_code
    log.debug('status code: %s, log: %s, reason: %s',
              status_code, ret.text, ret.reason)


def add_plan_entry(plan_id, suite_id, config_ids):
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
    request = {
        "suite_id": suite_id,
        "config_ids": config_ids,
        "runs": [
            {"config_ids": [c_id]} for c_id in config_ids
            ]
    }


    ret = requests.post(url,
                        headers=HEADER,
                        data=json.dumps(request),
                        auth=(LOGIN, KEY))
    status_code = ret.status_code
    log.info('status code: %s, log: %s, reason: %s',
             status_code, ret.text, ret.reason)


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
        ret = requests.post(url,
                            headers=HEADER,
                            data=json.dumps(request),
                            auth=(LOGIN, KEY))
        status_code = ret.status_code
        log.debug('status code: %s, log: %s, reason: %s',
                  status_code, ret.text, ret.reason)


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


def parse_report(report_path):
    """

    :param report: path to junit report
    :return: list of test cases name (string)
    """
    report = parse(report_path)

    testcases = ['.'.join([tcase.get('classname', ''),
                           tcase.get('name', '')])
                 for tcase in report.findall('testcase')]

    testcases = [t for t in testcases if t != '.']

    return testcases


def modify_testname(test_name, section):
    """
    Handle specific test names

    :param test_name: string
    :param section: test suite section
    :type section: string
    :return: string
    """

    test_name = re.sub(r'\(172.*\)', '', test_name)  # bizstorenode hack #FIXME
    test_name = re.sub(r'201*.*.*', '', test_name)  # remove date (supervisor)

    # Remove distrib in test name (supervisor hack)
    for distrib in OS:
        if distrib.lower() in test_name.lower():
            test_name = test_name.lower()
            test_name = re.sub(r'{0}'.format(distrib.lower()), '', test_name)

    # Handle random test names if possible
    for rand_tests in RANDOM_TEST_NAMES.get(section, []):
        if test_name.startswith(rand_tests):
            return rand_tests

    return test_name


def add_testcases(suite, tests, testrail_cases_name):
    """
    Add test case(s) to a test suite

    :param suite: testrail test suite (ex: "7.2")
    :type suite: string
    :param tests: tests to add
    :type tests: dictionary, each key is a section and contains a list of tests
    :param testrail_cases_name: test cases already in testrail test suite
    :type testrail_cases_name: list of string
    :return:
    """
    for section in tests:
        log.info('Section: %s', section)
        log.info('Suite: %s', suite)
        suite_id = get_suite(suite)
        log.info('Suite id: %s', suite_id)
        section_id = get_section(suite_id, section)
        log.info('Tests to be added: %s', tests)

        for test in tests[section]:
            test = modify_testname(test, section)
            log.info('Adding %s in section %s', test, section)
            ret = add_testcase(test, section_id, testrail_cases_name)
            if ret:
                testrail_cases_name.append(test)


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

    # Handle `Too many requests error`
    status_code = 429
    while status_code == 429:
        ret = requests.post(url,
                            headers=HEADER,
                            data=json.dumps(request),
                            auth=(LOGIN, KEY))
        status_code = ret.status_code
        log.info('status code: %s, log: %s, reason: %s',
                 status_code, ret.text, ret.reason)

    ret = json.loads(ret.text)
    log.info(ret)
    return ret.get('id')


def get_plan(version):
    """

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


def add_result(test_case, tests_db, run, section, version):
    """

    :param test_case: test case name found in report
    :type test_case: string
    :param tests_db: all tests related to current run
    :type tests_db: list of strin
    :param run: testrail run id
    :type: run: integer
    :param section: test suite section
    :type section: string
    :param version: test plan name
    :type version: string
    :return: result
    :rtype: dict
    """

    # Building test name
    name = test_case.get('name', '')
    classname = test_case.get('classname', '')

    name = '.'.join([classname, name])

    name = modify_testname(name, section)

    # Get elapsed time if set
    elapsed = test_case.get('time')

    # Get test case id
    for test in tests_db:
        if name == test['title']:
            test_id = test['id']
            break
    else:
        log.debug("%s: No test found", name)
        with open(NOT_FOUND_FILE, 'a+') as not_found:
            not_found.write("run: {0} version: {1} name: {2}\n".format(
                run, version, name
            ))
        return


    child = test_case.getchildren()

    # Set test status
    if child:
        child = child[0]
        status = child.tag
        if status == 'failure' or status == 'error':
            status_id = 5
        elif status == 'skipped':
            status_id = 6
        else:
            status_id = 1

        # Get message if exists
        attrib = child.attrib.get('message', '').encode('utf-8')

        if child.text:
            text = child.text.encode('utf-8')
        else:
            text = "No trace"

        message = '{0}\n## trace ##\n{1}'.format(attrib, text)

    else:
        status_id = 1
        message = 'OK'

    elapsed = int(float(elapsed))

    log.debug(message)
    log.debug('name: %s test_id: %s status_id:%s message:%s',
              name, test_id, status_id, message)

    result = {'test_id': test_id,
              'status_id': status_id,
              'comment': message,
              'version': version}

    if elapsed:
        result['elapsed'] = str(elapsed) + 's'

    log.debug(result)
    return result


def build_results(report, version, run, section, tests_db):
    """
    Given a report get a results dict

    :param report_path: path to the report
    :type report_path: string
    :param version: testrail test plan
    :type version: string
    :param run: corresponding test run
    :param section: testrail section
    :param tests_db: all test cases related to the test run
    :return results:
    :rtype: dict with one entry 'results', which value is a list of dict
    """
    report = parse(report.path)

    results_l = []

    for tcase in report.findall('testcase'):
        result = add_result(tcase, tests_db, run, section, version)
        results_l.append(result)

    # Remove empty result
    results_l = [r for r in results_l if r]

    results = {"results": results_l}

    return results


def put_results(version, run, report, distrib, tests_db):
    """

    :param version:
    :param run:
    :param reports: list of report objects
    :type reports: list of `report_obj` tuples
    :param tests_db:
    :return:
    """

    log.debug(tests_db)

    log.info('report: %s', report)

    number_of_res = 0

    if report.section and report.distrib == distrib:
        results = build_results(report, version, run, report.section, tests_db)
        nb_res = len(results['results'])
        number_of_res += nb_res

        # POST results dictionary
        url = URL_BASE + "index.php?/api/v2/add_results/{0}".format(run)
        status_code = 429
        while status_code == 429:
            log.info('POST results:\nReport:%s\nNb results: %s',
                     report, nb_res)
            ret = requests.post(url,
                                headers=HEADER,
                                data=json.dumps(results),
                                auth=(LOGIN, KEY))
            status_code = ret.status_code

            log.debug('status_code:%s text: %s reason: %s',
                      ret.status_code, ret.text, ret.reason)

    return number_of_res


def get_reports(version):
    """

    :param version: example: staging-7.1.0.r17062621.69c5697.post-merge.00034526
    :return:
    """

    version = ''.join([URL_ARTIFACTS, version])

    url = os.path.join(version) + '/'
    tmp_dir = tempfile.mkdtemp()
    log.info(url)

    # Download all junit/report.xml in odr artifacts repo
    cmd = ('wget -l 10 -q -r -P {0} '
           '--progress=dot:style:mega --show-progress '
           '--accept=*.xml {1}').format(tmp_dir, url)

    log.info(cmd)

    out = subprocess.call(cmd.split())

    paths = find("*.xml", tmp_dir)
    log.info("Reports downloaded from %s:\n%s",
             url, '\n'.join(paths))

    return out, paths


def find(pattern, path):
    """
    Given a pattern, return all the files that match in the given path

    :param pattern:
    :param path:
    :return:
    """
    result = []
    for root, _, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                result.append(os.path.join(root, name))
    return result


def put_results_from_artifacts(version, suite, reports):
    """
    :param version:
    :param artifacts:
    :param suite:
    :return:
    """
    nb_res = 0

    start = time.time()

    plan = get_plan(version)
    suite_id = get_suite(suite)

    if not plan:
        milestone = suite
        add_plan(version, milestone)
        plan = get_plan(version)
        add_plan_entry(plan, suite_id, [1, 2, 3])

    assert plan, "No plan found linked to test suite {0}".format(
        version)

    # Loop on distribution (one distrib per run)
    for distrib in OS:
        log.info(distrib)

        run = get_run(plan, distrib)
        assert run, "No run found linked to plan {0}".format(plan)

        tests_db = get_tests(run)

        for report in reports:
            if report.distrib == distrib.lower():
                nb_part = put_results(
                    version, run, report, distrib.lower(), tests_db
                )
                nb_res += nb_part

    duration = time.time() - start
    log.info("%s Results uploaded in %s seconds", nb_res, duration)


def check_test_case(report, testrail_names):
    """
    Check tests in report are in testrail test suite

    :param report: path report
    :type report: string
    :param testrail_names: test cases already in testrail test suite
    :type testrail_names: list of string
    :return missing_tests: missing tests
    :rtype: list of string
    """

    log.info('check test cases in %s', report.path)
    test_cases = parse_report(report.path)

    missing_tests = [test for test in test_cases if test not in testrail_names]

    return missing_tests


def check_test_cases(reports, suite):
    """
    Check tests in report are present in testrail

    :param reports: list of reports
    :param report_path_list: list of `report_obj` tuples
    :return missing_tests: tests that are missing
    :rtype: dictionary
    """
    missing_tests = defaultdict(list)

    log.info('Get cases from suite: %s', suite)
    testrail_cases = get_cases(suite)
    testrail_names = [test['title'] for test in testrail_cases]

    for report in reports:
        section = report.section
        log.info("report: %s", report)
        log.info("section: %s", section)

        if section:
            log.debug('check cases in %s', report)
            missing = check_test_case(report, testrail_names)

            if missing:
                missing_tests[section].extend(missing)
                # Avoid doublon
                missing_tests[section] = list(set(missing_tests[section]))

    return missing_tests, testrail_names


def arg_parse():
    """
    Parse script arguments

    """
    epilog = r"""
    You could use this script to:
    1. Add test cases to a test suite:

       /!\ section and distribution MUST be in the report path
       [mvelay@8b31e ~]$ python {0} -t -c 7.1 -r {1}

    2. Add results
       a. directly from an artifact url
       [mvelay@8b31e ~]$ python {0} -u  -c 7.2 -v {2} -a {2}

    b. from local junit report(s)
       /!\ section and distribution MUST be in the report path
       [mvelay@8b31e ~]$ python {0} -u -c 7.1 -v 7.1.0_rc5 -r {1}

    """.format(sys.argv[0],
               'reports/report_$section_centos7_710_rc5.xml',
               'bitbucket:7.2.0.0_rc2')

    parser = ArgumentParser(epilog=epilog,
                            formatter_class=RawDescriptionHelpFormatter)

    parser.add_argument(
        '-t', '--add_tests',
        help='Add test cases to a test suite',
        action='store_true',
        required=False)

    parser.add_argument(
        '-u', '--add_results',
        help='Add results to a testrail test run',
        action='store_true',
        required=False)

    parser.add_argument(
        '-c', '--cases',
        help='testrail testsuite, ex: "7.1"',
        required=False)

    parser.add_argument(
        '-v', '--version',
        help='RING version, linked to a testrail run, ex:"7.1.0_rc5"',
        required=False)

    parser.add_argument(
        '-a', '--artifacts',
        help="""
        Url artifacts
        Example: staging-7.1.0.r170626213221.69c5697.post-merge.00034526""",
        required=False)

    parser.add_argument(
        '-r', '--reports',
        help="Path to junit report",
        nargs='*',
        required=False)

    args = parser.parse_args()

    return parser, args


def struc_reports(reports):
    """
    Build report objects

    report_obj namedtuple has 3 fields:
    - path
    - section
    - distrib

    :param reports: report paths list
    :type reports: list
    :return: list of report object
    :rtype: list of `report_obj`
    """
    # Handle directory as report argument
    if isinstance(reports, str):
        reports = [reports]

    dirs = [r for r in reports if os.path.isdir(r)]

    log.info(dirs)

    # Convert each directory to a list of xml report
    for c_dir in dirs:
        reports_xml = find("*.xml", c_dir)
        log.info(reports_xml)
        reports.remove(c_dir)
        reports.extend(reports_xml)

    reports_l = []

    for report in reports:
        c_section = None
        c_distrib = None
        for section in SECTIONS:
            if 'undelete' in report:
                # fuse or cifs could be in the path
                c_section = 'undelete'
            elif 'versioning' in report:
                # fuse or cifs could be in the path
                c_section = 'versioning'
            elif section in report:
                c_section = section

        for distrib in OS:
            if distrib.lower() in report:
                c_distrib = distrib.lower()
                break
        else:
            # Handle particular cases here
            if c_section == 'robot_framework':
                # Distrib is not in the path
                c_distrib = 'trusty'

        reports_l.append(report_obj(report, c_section, c_distrib))

    return reports_l


def print_log_file(func):
    """
    Decorator
    Print path to general log file
    Log exception during func execution

    :param func: function to decorate
    :return wrapper decorated function
    """
    log.info('Log report available: %s', LOG_FILE)

    def wrapper(*args, **kwargs):
        """
        Decorated function
        """
        try:
            func(*args, **kwargs)
        except Exception as exc:
            log.exception(exc)
            raise Exception(exc)
        finally:
            log.info('Log report available: %s', LOG_FILE)

    return wrapper


@print_log_file
def main():
    """
    Entry point
    """
    # Parse arguments
    parser, args = arg_parse()
    add_tests = args.add_tests
    add_results = args.add_results
    cases = args.cases
    version = args.version
    reports = args.reports
    artifacts = args.artifacts

    # Handle various parameters combinations
    if not add_results and not add_tests:
        parser.print_help()
        raise ArgumentError(None, 'Please add tests (-t) or results (-u)')

    if add_results and add_tests:
        parser.print_help()
        raise ArgumentError(None, 'Please add tests (-t) OR results (-u)')

    elif add_tests:
        if cases and reports:
            # Build reports as object
            reports = struc_reports(reports)

            missing, present = check_test_cases(reports, cases)

            # Add missing tests cases in test suite if need be
            add_testcases(cases, missing, present)

        else:
            raise ArgumentError(
                None,
                'Need a testsuite AND a report'
            )

    elif add_results and version and cases:
        if artifacts:

            log.info("Version: %s", version)
            log.info("Artifacts: %s", artifacts)
            log.info("Suite: %s", cases)

            # Get all reports from artifacts
            out, reports = get_reports(artifacts)
            log.debug("Get reports output: %s", out)

            # Build reports as object
            reports = struc_reports(reports)

            # Get missing tests
            missing, present = check_test_cases(reports, cases)
            log.info('Missing tests: %s', missing)

            # Add missing tests cases in test suite if need be
            add_testcases(cases, missing, present)

            # Push result on testrail
            put_results_from_artifacts(version, cases, reports)

        elif reports:
            # Build reports as object
            reports = struc_reports(reports)

            log.info(version)
            log.debug(reports)
            plan = get_plan(version)
            assert plan, "No plan found linked to test suite {0}".format(
                version)

            for report in reports:
                log.info(report)
                log.info(report.distrib)
                run = get_run(plan, report.distrib)
                assert run, "No run found linked to plan {0}".format(plan)

                tests_db = get_tests(run)
                nb_tests = put_results(
                    version, run, report, report.distrib, tests_db
                )
                log.info("%s Results uploaded", nb_tests)
        else:
            raise ArgumentError(
                None,
                'Need an artifact url OR a list of reports)'
            )
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
