#!/usr/bin/env python
# coding: utf-8

"""
Testrail for scality
"""

from argparse import ArgumentParser, ArgumentError, RawDescriptionHelpFormatter
from collections import defaultdict, namedtuple
import fnmatch
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from xml.etree.ElementTree import parse

from testrail_utils import (
    LOG_FILE,
    URL_ARTIFACTS,
    URL_ARTIFACTS_PUBLIC,
    URL_ARTIFACTS_OLD,
    add_plan,
    add_plan_entry,
    add_testcase,
    close_plan,
    close_plans,
    log,
    get_cases,
    get_configs,
    get_entries_id,
    get_suite,
    get_section,
    get_open_plan,
    get_plan,
    get_run,
    get_sections,
    get_tests,
    put_results,
    update_plan_entry,
)

OS = ("xenial", "centos7")

STATUS_ID = {
    "passed": 1,
    "failed": 5,
    "skipped": 6,
    "known_failed_ok": 7,
    "known_failed": 10,
    "flaky_passed": 11,
    "flaky_failed": 12,
}

report_obj = namedtuple("report", ["path", "section", "distrib"])


def parse_report(report_path):
    """

    :param report_path: path to junit report
    :return: list of test cases name (string)
    """
    report = parse(report_path)

    testcases = [
        ".".join([tcase.get("classname", ""), tcase.get("name", "")])
        for tcase in report.findall(".//testcase")
    ]

    testcases = [t for t in testcases if t != "."]

    return testcases


def add_testcases(suite, tests, testrail_cases_name):
    """
    Add test case(s) to a test suite

    :param suite: testrail test suite (ex: "7.2")
    :type suite: string
    :param tests: tests to add
    :type tests: dictionary, each key is a section and contains a list of tests
    :param testrail_cases_name: test cases already in testrail test suite
    :type testrail_cases_name: list of string
    :return: nb_new_tests
    :rtype: integer
    """
    start = time.time()
    nb_new_tests = 0

    for section in tests:
        log.info("Section: %s", section)
        log.info("Suite: %s", suite)
        suite_id = get_suite(suite)
        log.info("Suite id: %s", suite_id)
        section_id = get_section(suite_id, section)
        log.info("Tests to be added: %s", tests)

        for test in tests[section]:
            log.info("Adding %s in section %s", test, section)
            ret = add_testcase(test, section_id, testrail_cases_name)
            if ret == 200:
                nb_new_tests += 1
                testrail_cases_name.append(test)
            else:
                log.info("%s test not added", test)

    duration = time.time() - start

    return nb_new_tests, duration


def add_result(
    test_case, tests_db, run, section, version, description, flaky, known_failed
):
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
    name = test_case.get("name", "")
    classname = test_case.get("classname", "")

    name = ".".join([classname, name])

    # Get elapsed time if set
    elapsed = test_case.get("time")

    # Get test case id
    for test in tests_db:
        if name == test["title"]:
            test_id = test["id"]
            break
    else:
        log.debug("%s: No test found", name)
        return

    child = test_case.getchildren()

    message = description

    # Set test status
    if child:
        child = child[0]
        status = child.tag
        if status == "failure" or status == "error":
            status_id = STATUS_ID["failed"]
        elif status == "skipped":
            status_id = STATUS_ID["skipped"]
        else:
            status_id = STATUS_ID["passed"]

        # Get message if exists
        attrib = child.attrib.get("message", "").encode("utf-8")
        attrib = textwrap.dedent(attrib)
        if child.text:
            text = child.text.encode("utf-8")
        else:
            text = "No trace"

        message += "***\n# Error message\n{0}\n***\n# Traceback\n{1}\n***\n".format(
            attrib, text
        )
        message = textwrap.dedent(message)

    else:
        status_id = STATUS_ID["passed"]
        message += "OK"

    # Handle known failed tests
    if name in known_failed:
        if status_id == STATUS_ID["failed"]:
            status_id = STATUS_ID["known_failed"]
            message = "*** Known failed test ***\n%s" % message
        elif status_id == STATUS_ID["passed"]:
            status_id = STATUS_ID["known_failed_ok"]
            message = "*** Known failed test PASSED (!)***\n%s" % message

    # Handle flaky tests
    elif name in flaky:
        if status_id == STATUS_ID["passed"]:
            status_id = STATUS_ID["flaky_passed"]
            message = "*** flaky test OK ***\n%s" % message
        elif status_id == STATUS_ID["failed"]:
            status_id = STATUS_ID["flaky_failed"]
            message = "*** flaky test FAILED ***\n%s" % message

    elapsed = int(float(elapsed))

    log.debug(message)
    log.debug(
        "name: %s test_id: %s status_id:%s message:%s",
        name,
        test_id,
        status_id,
        message,
    )

    result = {
        "test_id": test_id,
        "status_id": status_id,
        "comment": message,
        "version": version,
    }

    if elapsed:
        result["elapsed"] = str(elapsed) + "s"

    log.debug(result)
    return result


def build_results(
    report, version, run, section, tests_db, description, flaky, known_failed
):
    """
    Given a report get a results dict

    :param report: path to the report
    :type report: string
    :param version: testrail test plan
    :type version: string
    :param run: corresponding test run
    :param section: testrail section
    :param tests_db: all test cases related to the test run
    :param description: tests description
    :param flaky: list of case id referenced as "flaky"
    :param known_failed: list of case id referenced as "known_failed"
    :return results:
    :rtype: list of results
    """
    report = parse(report.path)

    results_l = []

    for tcase in report.findall(".//testcase"):
        result = add_result(
            tcase, tests_db, run, section, version, description, flaky, known_failed
        )
        results_l.append(result)

    # Remove empty result
    results_l = [r for r in results_l if r]

    return results_l


def get_reports(version, distribs, url_artifacts=URL_ARTIFACTS):
    """
    Get all reports from artifacts url

    :param version: example: staging-7.1.0.r17062621.69c5697.post-merge.00034526
    :type version: string
    :param distribs: list of expected OS
    :type distribs: list of strings
    :return:
    """
    start = time.time()

    version = "".join([url_artifacts, version])

    url = os.path.join(version) + "/"
    tmp_dir = tempfile.mkdtemp()
    log.info(url)

    # Download all junit/report.xml in odr artifacts repo
    cmd = (
        "wget --tries=50 -l 10 -r -P {0} "
        "--progress=dot:mega "
        "--accept=*.xml,report.json {1}"
    ).format(tmp_dir, url)

    log.info(cmd)

    out = subprocess.call(cmd.split())
    log.info("wget output: %s", str(out))

    paths = find("*.xml", tmp_dir)

    # Filter on distribs
    paths = [path for path in paths if any(d.lower() in path for d in distribs)]

    # Trick to get global report
    if tmp_dir not in paths:
        paths.append(tmp_dir)

    log.info("Reports downloaded from %s:\n%s", url, "\n".join(paths))

    duration = time.time() - start

    return out, paths, duration


def get_related_artifacts(version, url_artifacts=URL_ARTIFACTS):
    """
    Get related artifacts if exists (for postmerge build essentially)

    :param version: example: staging-7.1.0.r17062621.69c5697.post-merge.00034526
    :type version: string
    :param distribs: list of expected OS
    :type distribs: list of strings
    :return:
    """
    version = "".join([url_artifacts, version])

    url = os.path.join(version) + "/.related_artifacts/"
    tmp_dir = tempfile.mkdtemp()
    log.info(url)

    # Download the related artifacts url
    cmd = ("wget --tries=50 -l 3 -r -P {0} " "--progress=dot:mega " "{1}").format(
        tmp_dir, url
    )

    log.info(cmd)

    out = subprocess.call(cmd.split())
    log.info("wget output: %s", out)

    # Retrieve related artifacts in index.html directly
    related_artifacts_index = find("index.html", tmp_dir)

    if related_artifacts_index:
        index_file = related_artifacts_index[0]
    else:
        return

    related_artifacts = parse_index_file(index_file)

    return related_artifacts


def parse_index_file(path):
    """
    Parse index.html to retrieve premerge artifacts

    :param path: index.html path
    :type path: string
    :return premerge_name: premerge artifacts name
    :rtype: string
    """
    with open(path, "r") as content:
        try:
            premerge_name = re.search('href="./(.*)">', content.read()).group(1)
        except Exception as exc:
            log.info(exc)
            return

    return premerge_name


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


def get_flagged_tests(suite, flag):
    """
    Return flagged tests in testrail
    We are looking for `References` field value in testcases

    :param suite: 
    :type suite: string
    :param flag: manually set in testrail 
    :type flag: string, such as "flaky", "known_failed", etc
    :rtype: list 
    """
    flagged = []
    
    suite_id = get_suite(suite)

    for section in get_sections(suite_id):
        cases_suite = get_cases(suite, section.get("name"))
        cases = [case.get("id") for case in cases_suite]
        
        # Retrieve flagged tests from DB
        flag_cases = [
            case.get("title")
            for case in cases_suite
            if case.get("refs", "") is not None and flag in case.get("refs")
        ]
        flagged.extend(flag_cases)
        
    return flagged

def put_results_from_reports(version, suite, milestone, reports, distribs, description):
    """

    :param version:
    :param suite:
    :param milestone:
    :param reports:
    :param distribs:
    :param description:
    :return:
    """
    start = time.time()
    nb_res = 0

    suite_id = get_suite(suite)
    sections = get_sections(suite_id)
    log.info("sections: %s ", sections)

    flaky = get_flagged_tests(suite, "flaky")
    known_failed = get_flagged_tests(suite, "known_failed")

    plan = get_open_plan(version)

    if not plan:
        add_plan(version, milestone, description)
        plan = get_plan(version)
        configs = get_configs()[0]["configs"]
        config_ids = [g["id"] for g in configs]
        add_plan_entry(plan, suite_id, config_ids)
    assert plan, "No plan found linked to test suite {0}".format(version)

    entries_id = get_entries_id(plan)
    log.info("entries id: %s", entries_id)
    for entry_id, config in entries_id:
        log.info("Update config: %s run (entry_id): %s", config, entry_id)
        update_plan_entry(plan, entry_id, description)

    # Loop on distribution (one distrib per run)
    for distrib in distribs:
        log.info(distrib)
        run = get_run(plan, distrib)
        assert run, "No run found linked to plan {0}".format(plan)

        tests_db = get_tests(run)
        # Loop on report related to distrib
        for report in reports:
            if report.distrib == distrib.lower() and report.section:
                results_c = build_results(
                    report,
                    version,
                    run,
                    report.section,
                    tests_db,
                    description,
                    flaky,
                    known_failed,
                )
                log.info("%s: %s results", report, len(results_c))

                if results_c:
                    nb_per_slice = 1000
                    nb_slices = len(results_c) / nb_per_slice + 1
                    # Put results by batch
                    for idx in range(nb_slices):
                        c_results = results_c[
                            nb_per_slice * idx : nb_per_slice * (idx + 1)
                        ]
                        nb_res_distrib = put_results(run, c_results, tests_db)
                        nb_res += nb_res_distrib
    duration = time.time() - start

    return nb_res, duration, plan


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

    log.info("check test cases in %s", report.path)
    test_cases = parse_report(report.path)

    missing_tests = [test for test in test_cases if test not in testrail_names]

    return missing_tests


def check_test_cases(reports, suite):
    """
    Check tests in report are present in testrail

    :param reports: list of reports
    :param suite: testrail suite
    :return
        missing_tests: tests that are missing,
        testrail_name: existing tests
        duration
    :rtype: tuple (dict, list, integer)
    """
    start = time.time()

    missing_tests = defaultdict(list)

    log.info("Get cases from suite: %s", suite)

    suite_id = get_suite(suite)
    sections = get_sections(suite_id)

    testrail_cases = get_cases(suite)
    testrail_names = [test.get("title") for test in testrail_cases]

    for report in reports:
        section = report.section
        log.info("report: %s", report)
        log.info("section: %s", section)

        if section:
            log.debug("check cases in %s", report)
            missing = check_test_case(report, testrail_names)

            if missing:
                missing_tests[section].extend(missing)
                # Avoid doublon
                missing_tests[section] = list(set(missing_tests[section]))
        else:
            log.warning("""
            No section found for %s
            Section MUST be in the report name
            Available sections are: %s""", report.path, [section.get('name') for section in sections])


    duration = time.time() - start

    return missing_tests, testrail_names, duration


def arg_parse():
    """
    Parse script arguments

    """
    epilog = r"""
    You could use this script to:

    1. Add results
       a. directly from an artifact url
       [scality@8b31e ~]$ python {0} -u  -c 7.2 -v {3} -a {2}

       b. from local junit report(s)
       /!\ section and distribution MUST be in the report path
       [scality@8b31e ~]$ python {0} -u -c 7.1 -v {4} -r {1}

    2. Close plans according to a pattern
        (Close all 7.4.0.0 test plans)
        [scality@8b31e ~]$ python {0} -k 7.4.0.0-
    """.format(
        sys.argv[0],
        "reports/report_zimbra_centos7_710_rc5.xml",
        "bitbucket:scality:ring:promoted-7.2.0.0_rc2",
        "promoted-7.2.0.0_rc2",
        "7.1.0_rc5",
    )

    parser = ArgumentParser(epilog=epilog, formatter_class=RawDescriptionHelpFormatter)

    parser.add_argument(
        "-u",
        "--add_results",
        help="Add results to a testrail test run",
        action="store_true",
        required=False,
    )

    parser.add_argument(
        "-c", "--cases", help='testrail testsuite, ex: "7.1"', required=False
    )

    parser.add_argument(
        "-v",
        "--version",
        help='RING version, linked to a testrail run, ex:"7.1.0_rc5"',
        required=False,
    )

    parser.add_argument(
        "-a",
        "--artifacts",
        help="""
        Url artifacts
        Example: staging-7.1.0.r170626213221.69c5697.post-merge.00034526""",
        required=False,
    )

    parser.add_argument(
        "-r", "--reports", help="Path to junit report", nargs="*", required=False
    )

    parser.add_argument(
        "-d",
        "--distrib",
        help="""
        distribution(s),
        Example: centos7 centos6""",
        nargs="*",
        default=OS,
        required=False,
    )

    parser.add_argument(
        "-l",
        "--artifacts_location",
        help="""
        artifacts url,
        Example: https://artifacts.devsca.com/builds/bitbucket:scality:ring:promoted-5.1.9/""",
        nargs="*",
        default="",
        required=False,
    )

    parser.add_argument(
        "-k",
        "--close_plan",
        help="""
        close the current plan after upload
        """,
        action="store_true",
        required=False,
    )

    parser.add_argument(
        "-p",
        "--close_pattern_plans",
        help="""
        close plans with the given pattern,
        Example: 7.2.0.0-""",
        required=False,
    )

    parser.add_argument(
        "-m",
        "--milestone",
        help="""
        Specify testrail milestone
        Example: 7.4""",
        required=False,
    )

    parser.add_argument(
        "-o",
        "--old_artifacts",
        help="""
        Use the old artifacts url i.e https://artifacts.devsca.com/builds/
        """,
        action="store_true",
        required=False,
    )

    parser.add_argument(
        "-f",
        "--linkfile",
        help="""
        print resulting plan url to filename
        """,
        default="",
        required=False,
    )

    parser.add_argument(
        "-e",
        "--exclude_sections",
        help="""
        exclude testrail sections,
        Example: sprov bizstorenode""",
        nargs="*",
        default="",
        required=False,
    )

    parser.add_argument(
        "-b",
        "--base_url",
        help="""
        Artifacts private url""",
        required=False,
    )

    parser.add_argument(
        "-R",
        "--reason",
        default="",
        help="""
        Label for current run""",
        required=False,
    )

    args = parser.parse_args()

    return parser, args


def found_global_report(g_reports_l):
    """
    Found valid global report

    :param g_reports_l: potential global reports list
    :type g_reports_l: list of paths
    :return: global report path
    :rtype: string
    """
    reports = []
    log.debug("found_global_report")
    log.debug(g_reports_l)
    for report in g_reports_l:
        valid = True
        report_json = json.load(open(report, "r"))
        for task in report_json:
            # Check if 'steps' key is there
            try:
                steps = task["steps"]
                log.debug(steps)
            except (KeyError, TypeError):
                log.info("%s not a valid format for global report", report)
                valid = False
                break
        if valid:
            reports.append(report)

    return reports


def struc_reports(reports, suite, distribs, exclude_sections):
    """
    Build report objects

    report_obj namedtuple has 3 fields:
    - path
    - section
    - distrib

    :param reports: report paths list
    :type reports: list
    :param suite: test suite name in testrail, e.g. '7.2'
    :type suite: string
    :param distribs: os name(s)
    :type distribs: list of string
    :param exclude_sections: sections to ignore
    :type exclude_sections: list of strings
    :return: list of report object
    :rtype: list of `report_obj`
    """
    # Handle directory as report argument
    if isinstance(reports, str):
        reports = [reports]

    dirs = [r for r in reports if os.path.isdir(r)]

    # Convert each directory to a list of xml report
    global_reports = []
    for c_dir in dirs:
        reports_xml = find("*.xml", c_dir)
        global_reports = find("report.json", c_dir)
        reports.remove(c_dir)
        reports.extend(reports_xml)

    global_reports = found_global_report(global_reports)

    reports_l = []

    # Retrieve section names from testrail test suite
    suite_id = get_suite(suite)
    sections = get_sections(suite_id)
    sections_name = [
        s.get("name") for s in sections if s.get("name") not in exclude_sections
    ]

    log.info("Sections: %s", sections_name)

    for report in reports:
        c_section = None
        c_distrib = None
        for section in sections_name:
            if section in report:
                c_section = section

        for distrib in distribs:
            if distrib.lower() in report:
                c_distrib = distrib.lower()
                break

        reports_l.append(report_obj(report, c_section, c_distrib))

    return list(set(reports_l)), global_reports


def parse_global_report(global_report):
    """
    Parse global json report

    :param global_report: global report path
    :type global_report: string
    :return failed_steps: all failed steps
    :rtype: dictionary
    """
    failed_steps = {}

    report_json = json.load(open(global_report, "r"))
    log.info(report_json)
    for task in report_json:
        steps = task.get("steps")
        for step in steps:
            if step.get("failed"):
                step = step["step_name"]
                infos = task.get("task_infos")
                task = infos["task_name"]
                distrib = infos["permutation"]
                if step in ("setup", "requirements"):
                    key = "%s_%s_%s" % (task, distrib, step)
                    failed_steps[key] = {"os": distrib, "step": step}
    return failed_steps


def mass_tag_failed(failed_steps, version, suite, exclude_sections, desc):
    """
    Mass tag failed steps, 'setup' or 'requirements' for ODR

    :param failed_steps: failed steps listing
    :type failed_steps:  dictionary
    :param version: testrail version name
    :param suite: testrail test suite
    :param exclude_sections: sections to be ignored
    :param desc: upload description

    """
    plan = get_plan(version)

    # Retrieve section names from testrail test suite
    suite_id = get_suite(suite)
    sections = get_sections(suite_id)
    sections_name = [
        s.get("name") for s in sections if s.get("name") not in exclude_sections
    ]

    log.info("Check environment issues")

    for task, infos in failed_steps.items():
        # Initialize results list for this task
        results_l = []
        for section in sections_name:
            if section in task:
                s_task = section
            break
        else:
            log.info("No valid section found in testrail: %s", task)
            continue

        log.info("task: %s -> section found: %s", task, s_task)
        log.info("suite: %s", suite)

        # Get testrail section id
        cases = get_cases(suite, s_task)
        section_id = get_section(suite_id, s_task)

        distrib = infos["os"]
        step = infos["step"]

        # Handle setup and requirements failures
        if step == "setup":
            status_id = 8
        elif step == "requirements":
            status_id = 9
        else:
            raise Exception(
                'Mass tag step not handled, must be "setup" or "requirements"'
            )

        log.info(step)
        log.info(distrib)

        #  Get all tests related to the current test run
        run_id = get_run(plan, distrib)
        tests = get_tests(run_id)

        # List all test cases related to current section
        cases_name = [case["id"] for case in cases if case["section_id"] == section_id]

        # List all tests related to current section
        tests = [test for test in tests if test["case_id"] in cases_name]

        # Loop on all tests, build dict result and add to results list
        for test in tests:
            result = {
                "test_id": test["id"],
                "status_id": status_id,
                "comment": "{0}\n{1} failed".format(desc, step),
                "version": version,
            }
            results_l.append(result)

        # Put all results in one POST for this current task
        log.info("Put env issues: %s - %s - %s", s_task, distrib, step)
        nb_per_slice = 1000
        nb_slices = len(results_l) / nb_per_slice + 1
        for idx in range(nb_slices):
            put_results(
                run_id, results_l[nb_per_slice * idx : nb_per_slice * (idx + 1)], tests
            )


def print_log_file(func):
    """
    Decorator
    Print path to general log file
    Log exception during func execution

    :param func: function to decorate
    :return wrapper decorated function
    """
    log.info("Log report available: %s", LOG_FILE)

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
            log.info("Log report available: %s", LOG_FILE)

    return wrapper


@print_log_file
def main():
    """
    Entry point
    """
    # Parse arguments
    parser, args = arg_parse()
    add_results = args.add_results
    cases = args.cases
    version = args.version
    reports = args.reports
    artifacts = args.artifacts
    distribs = args.distrib
    exclude_sections = args.exclude_sections
    pattern_plans = args.close_pattern_plans
    upload_location = args.artifacts_location
    milestone = args.milestone
    old_artifacts = args.old_artifacts
    base_url = args.base_url
    linkfile = args.linkfile
    reason = args.reason

    if not milestone:
        milestone = cases

    if not distribs:
        distribs = OS

    if reports:
        reports = [r.decode("utf-8") for r in reports]

    # Handle various parameters combinations
    if not add_results and not pattern_plans:
        parser.print_help()
        raise ArgumentError(None, "Please add results (-u) or close plans (-k)")

    elif add_results and version and cases:
        log.info("Version: %s", version)
        log.info("Suite: %s", cases)

        if artifacts:
            if base_url:
                url_artifacts = os.path.dirname(base_url) + "/"
            elif old_artifacts:
                url_artifacts = URL_ARTIFACTS_OLD
            else:
                url_artifacts = URL_ARTIFACTS

            log.info("Artifacts: %s", artifacts)

            # Get all reports from artifacts
            out, reports, dur_g = get_reports(artifacts, distribs, url_artifacts)

            if not reports:
                raise Exception("No report found")
            log.debug("Get reports output: %s", out)

            upload_location = os.path.join(URL_ARTIFACTS_PUBLIC, artifacts)

        if reports:
            if not upload_location:
                upload_location = reports

            description = """
                ***\n
                # Upload infos #\n
                + Last upload: {0}\n
                + hostname: {1}\n
                + user: {2}\n
                + artifacts: [{3}]({3})\n
                + reason: {4}\n
                ***\n
                """.format(
                time.asctime(),
                socket.gethostname(),
                getpass.getuser(),
                upload_location,
                reason,
            )
            description = textwrap.dedent(description)

            # Build reports as object
            reports, global_reports = struc_reports(
                reports, cases, distribs, exclude_sections
            )

            log.info(version)
            log.info(reports)

            # Get missing tests
            missing, present, dur_c = check_test_cases(reports, cases)
            nb_missing = sum([len(tests) for _, tests in missing.items()])
            log.info("%s Missing tests: %s", nb_missing, missing)

            # Add missing tests cases in test suite if need be
            nb_new_tests, dur_a = add_testcases(cases, missing, present)

            # Put results into testrail DB
            nb_res, dur_p, plan = put_results_from_reports(
                version, cases, milestone, reports, distribs, description
            )

            # Handle step failures
            # Put env_issue status
            log.info("g_reports %s", global_reports)
            for g_report in global_reports:
                failed_steps = parse_global_report(g_report)
                log.info("failed steps: %s", failed_steps)
                mass_tag_failed(
                    failed_steps, version, cases, exclude_sections, description
                )

            if artifacts:
                log.info("* Download reports in %s seconds", dur_g)

            log.info("* Check existing test cases in %s seconds", dur_c)

            if nb_new_tests:
                log.info("* Add %s new tests in %s seconds", nb_new_tests, dur_a)

            log.info("* Put %s results in %s seconds", nb_res, dur_p)

            if args.close_plan:
                log.info("Closing plan %s", plan)
                close_plan(plan)

            #  Display test plan url
            url_plan = "https://scality.testrail.net/index.php?/plans/view/{0}".format(
                plan
            )
            log.info("Testrail plan: %s", url_plan)
            if linkfile:
                with open(linkfile, "w") as file_:
                    file_.write(url_plan)

        else:
            raise ArgumentError(None, "Need an artifact url OR a list of reports)")
    elif pattern_plans:
        close_plans(pattern_plans)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
