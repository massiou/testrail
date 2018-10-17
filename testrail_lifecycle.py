#!/usr/bin/env python3
# coding: utf-8

"""
Testrail lifecycle policy
"""
from argparse import (
    ArgumentParser,
    RawDescriptionHelpFormatter
)
import time

from testrail_utils import (
    close_plan,
    get_plans_created_before,
    delete_plan
)

# Globals
EXCLUDE_PATTERNS = ['promoted', 'rc', 'pw', 'postmerge', 'post-merge']


def arg_parse():
    """
    Parse script arguments
    """
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        usage='%(prog)s [options]'
    )

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
        '-a', '--action',
        help="available actions: 'garbage' or 'close'",
        required=False,
    )

    parser.add_argument(
        '-u', '--duration',
        help='Garbage loop duration (seconds)',
        type=int,
        required=False,
        default=300)

    args = parser.parse_args()

    return parser, args


def trash(duration: int, retention: int, exclude_patterns: list) -> tuple:
    """
    Delete plans according to creation date and name

    :return: list of successfully deleted plans
    """
    start = time.time()
    timestamp = start - retention

    plans = get_plans_created_before(timestamp)
    delete_plans = []
    ignore_plans = []

    c_duration = 0
    offset = 0
    while plans and (c_duration < duration):
        c_duration = int(time.time()) - start

        for plan in plans:
            plan_id = plan.get('id')
            url = plan.get('url')

            # Ignored plans according to exclude patterns
            if any(c in plan.get('name') for c in exclude_patterns):
                ignore_plans.append(plan.get('name'))
                print("keep {0}".format(plan.get('name')))
            else:
                # Delete plans
                print("deleting {0}".format(url))
                ret = delete_plan(plan_id)
                if ret.status_code == 200:
                    print("deleted {0}".format(url))
                    delete_plans.append(plan.get('name'))

        # Set the plans offset
        offset += len(ignore_plans)

        if len(plans) == len(ignore_plans):
            break

        plans = get_plans_created_before(timestamp, offset)

    return delete_plans, ignore_plans


def close(retention: int, duration: int) -> list:
    """
    Close open plans

    :param retention: retention time before closing
    :type retention: int

    :return: list of deleted plans
    :rtype: list
    """
    start = time.time()
    timestamp = time.time() - retention

    plans = get_plans_created_before(timestamp)
    open_plans = [plan for plan in plans if not plan.get('is_completed')]

    closed = []
    c_duration = 0
    offset = 0
    while plans and (c_duration < duration):
        c_duration = int(time.time()) - start

        for plan in open_plans:
            print("Closing: {0} ...".format(plan.get("url")))
            ret = close_plan(plan.get("id"))
            if ret.status_code == 204:
                closed.append(plan.get("url"))

        # Set the plans offset
        offset += len(plans)
        plans = get_plans_created_before(timestamp, offset)
        open_plans = [plan for plan in plans if not plan.get('is_completed')]
    return plans


def main() -> None:
    """
    Entry point
    """
    # Parse arguments
    parser, args = arg_parse()
    print(args)
    action = args.action
    excl = args.exclude
    retention = args.retention_time
    duration = args.duration

    # Launch action
    if action == 'garbage':
        delete, kept = trash(
            duration=duration, retention=retention, exclude_patterns=excl
        )
        print("deleted plans:\n{0}".format(delete))
        print("kept plans:\n{0}".format(kept))

    elif action == 'close':
        closed = close(retention=retention, duration=duration)
        print("closed plans:\n{0}".format(closed))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
