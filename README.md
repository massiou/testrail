Testrail lifecycle management
=============================

## Purpose

Useful script to automate lifecycle management whether to close or delete runs

## Usage

``` bash
usage: testrail_lifecycle.py [options]

optional arguments:
  -h, --help            show this help message and exit
  -x EXCLUDE [EXCLUDE ...], --exclude EXCLUDE [EXCLUDE ...]
                        list of exclude patterns
  -r RETENTION_TIME, --retention_time RETENTION_TIME
                        retention time
  -a ACTION, --action ACTION
                        available actions: 'garbage' or 'close'
  -u DURATION, --duration DURATION
                        Garbage loop duration (seconds)
```

## Examples

Close all open runs older than 15 days
``` bash
$> testrail_lifecycle.py -r 1296000 -a "close"
```

Delete all runs older than 6 months (except if `promoted` or `rc` is in the run name)
``` bash
$> testrail_lifecycle.py -a "garbage" -x "promoted" "rc"
```


Testrail upload
===============

## Usage


``` bash
usage: testrail_upload.py [-h] [-u] [-c CASES] [-v VERSION] [-a ARTIFACTS]
                          [-r [REPORTS [REPORTS ...]]]
                          [-d [DISTRIB [DISTRIB ...]]]
                          [-l [ARTIFACTS_LOCATION [ARTIFACTS_LOCATION ...]]]
                          [-k] [-p CLOSE_PATTERN_PLANS] [-m MILESTONE] [-o]
                          [-f LINKFILE]
                          [-e [EXCLUDE_SECTIONS [EXCLUDE_SECTIONS ...]]]
                          [-b BASE_URL]

optional arguments:
  -h, --help            show this help message and exit
  -u, --add_results     Add results to a testrail test run
  -c CASES, --cases CASES
                        testrail testsuite, ex: "7.1"
  -v VERSION, --version VERSION
                        RING version, linked to a testrail run, ex:"7.1.0_rc5"
  -a ARTIFACTS, --artifacts ARTIFACTS
                        Url artifacts Example:
                        staging-7.1.0.r170626213221.69c5697.post-
                        merge.00034526
  -r [REPORTS [REPORTS ...]], --reports [REPORTS [REPORTS ...]]
                        Path to junit report
  -d [DISTRIB [DISTRIB ...]], --distrib [DISTRIB [DISTRIB ...]]
                        distribution(s), Example: centos7 centos6
  -l [ARTIFACTS_LOCATION [ARTIFACTS_LOCATION ...]], --artifacts_location [ARTIFACTS_LOCATION [ARTIFACTS_LOCATION ...]]
                        artifacts url, Example: https://artifacts.devsca.com/b
                        uilds/bitbucket::ring:promoted-5.1.9/
  -k, --close_plan      close the current plan after upload
  -p CLOSE_PATTERN_PLANS, --close_pattern_plans CLOSE_PATTERN_PLANS
                        close plans with the given pattern, Example: 7.2.0.0-
  -m MILESTONE, --milestone MILESTONE
                        Specify testrail milestone Example: 7.4
  -o, --old_artifacts   Use the old artifacts url i.e
                        https://artifacts.devsca.com/builds/
  -f LINKFILE, --linkfile LINKFILE
                        print resulting plan url to filename
  -e [EXCLUDE_SECTIONS [EXCLUDE_SECTIONS ...]], --exclude_sections [EXCLUDE_SECTIONS [EXCLUDE_SECTIONS ...]]
                        exclude testrail sections, Example: sprov bizstorenode
  -b BASE_URL, --base_url BASE_URL
                        Artifacts private url

    You could use this script to:

    1. Add results
       a. directly from an artifact url
       [@8b31e ~]$ python ./testrail_upload.py -u  -c 7.2 -v promoted-7.2.0.0_rc2 -a bitbucket::ring:promoted-7.2.0.0_rc2

       b. from local junit report(s)
       /!\ section and distribution MUST be in the report path
       [@8b31e ~]$ python ./testrail_upload.py -u -c 7.1 -v 7.1.0_rc5 -r reports/report_zimbra_centos7_710_rc5.xml

    2. Close plans according to a pattern
        (Close all 7.4.0.0 test plans)
        [@8b31e ~]$ python ./testrail_upload.py -k 7.4.0.0-
```