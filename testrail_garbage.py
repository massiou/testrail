#!/usr/bin/env python
# coding: utf-8

"""
Testrail purge
"""
from argparse import (
    ArgumentParser,
    RawDescriptionHelpFormatter
)
import time

import requests

from testrail_utils import (
    get_plans_created_before,
    delete_plan
)

# Globals
EXCLUDE_PATTERNS = ['promoted', 'rc', 'pw', 'postmerge', 'post-merge']

session = None


def arg_parse():
    """
    Parse script arguments
    """
    parser = ArgumentParser(formatter_class=RawDescriptionHelpFormatter)

    parser.add_argument(
        '-x', '--exclude',
        nargs='+',
        help='list of exclude patterns',
        required=False,
        default=EXCLUDE_PATTERNS
    )

    parser.add_argument(
        '-r', '--retention_time',
        help="retention time",
        type=int,
        required=False,
        default=2592000
    )

    parser.add_argument(
        '-u', '--duration',
        help='Garbage loop duration (seconds)',
        type=int,
        required=False,
        default=300)

    args = parser.parse_args()

    return parser, args


def main(timeout, retention, exclude_patterns):
    """
    Delete plans according to creation date and name

    :return: list of successfully deleted plans
    """
    timestamp = time.time() - retention

    plans = get_plans_created_before(timestamp)
    start = time.time()
    duration = 0

    while plans and (duration < timeout):
        delete_plans = []
        ignore_plans = []
        duration = int(time.time()) - start

        for plan in plans:
            plan_name, plan_id, _ = plan
            if any(c in plan_name for c in exclude_patterns):
                ignore_plans.append(plan)
                print "keep {0}".format(plan)
            else:
                print "deleting {0}".format(plan)
                ret = delete_plan(plan_id)
                if ret.status_code == 200:
                    print "deleted {0}".format(plan)
                    delete_plans.append(plan)
        offset = len(ignore_plans)

        if len(plans) == len(ignore_plans):
            break

        plans = get_plans_created_before(timestamp, offset)

        print "DELETED: {0}".format(delete_plans)
        print "KEPT: {0}".format(ignore_plans)


if __name__ == '__main__':
    # Parse arguments
    _, args = arg_parse()
    print args
    exclude = args.exclude
    retetion_time = args.retention_time
    duration = args.duration

    # Launch garbage
    main(timeout=duration, retention=retetion_time, exclude_patterns=exclude)






