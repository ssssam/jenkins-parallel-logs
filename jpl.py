#!/usr/bin/env python3

import argparse
import json
import logging
import os
import pathlib
import string
import sys
import urllib.parse

import requests

log = logging.getLogger()


def argument_parser():
    parser = argparse.ArgumentParser("Query Jenkins parallel job logs")
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--only-icon-color', type=str, metavar="COLOR",
            help="Filter by icon color, e.g. 'red' to get only failed build steps")

    parser.add_argument('--job', metavar="PATH", type=str, required=True,
            help="Job name or path.")
    parser.add_argument('--build', metavar="NUMBER", type=int, required=True,
            help="Build number.")
    parser.add_argument('--outdir', metavar="DIR", type=str, required=True,
            help="Directory to write log files. Must be empty, created if needed.")
    return parser


def build_path(job_name, build_number):
    parts = []
    for p in job_name.split('/'):
        parts.append('job')
        parts.append(p)
    parts.append(str(build_number))
    return '/'.join(parts) + '/'


def fetch_build_info(jenkins_url, build_path):
    url = urllib.parse.urljoin(jenkins_url, build_path)
    url = urllib.parse.urljoin(url, 'api/json?depth=2')
    log.debug("Query: %s", url)

    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def fetch_step_html(jenkins_url, node_path):
    url = urllib.parse.urljoin(jenkins_url, node_path)
    url = urllib.parse.urljoin(url, "log")
    log.debug("Query: %s", url)

    response = requests.get(url)
    if response.status_code == 404:
        log.debug("No log file for %s", node_path)
    else:
        response.raise_for_status()
        return response.text


class DataError(RuntimeError):
    pass


def expect_class(item, name):
    if item['_class'] != name:
        raise DataError("Expected class {}, got {}".format(
            name, item['_class']))

def find_class(class_list, name):
    for item in class_list:
        if item.get('_class') == name:
            return item
    raise DataError("Couldn't find class {} in list".format(name))



class BuildStep:
    def __init__(self, id_str, url, display_name, branch_name):
        self.id_str = id_str
        self.url = url
        self.display_name = display_name
        self.branch_name = branch_name


STEP_NODE_TYPES = ['StepStartNode', 'StepAtomNode', 'StepEndNode']
STEP_NODE_CLASSES = [
    'org.jenkinsci.plugins.workflow.cps.nodes.{}'.format(t)
    for t in STEP_NODE_TYPES
]


def find_step_nodes(build_info):
    expect_class(build_info, 'org.jenkinsci.plugins.workflow.job.WorkflowRun')
    actions = build_info['actions']
    flow_graph = find_class(actions, 'org.jenkinsci.plugins.workflow.job.views.FlowGraphAction')
    nodes = flow_graph['nodes']

    node_id_map = {}
    for node in nodes:
        if node['_class'] in STEP_NODE_CLASSES:
            node_id = node['id']
            node_id_map[node_id] = node
    return node_id_map


def branch_name(node_id_map, node):
    MARKER = 'Branch: '
    NO_BRANCH = '_'
    if node['displayName'].startswith(MARKER):
        return node['displayName'][len(MARKER):]
    elif len(node['parents']) > 0:
        first_parent = node_id_map[node['parents'][0]]
        return branch_name(node_id_map, first_parent)
    else:
        return NO_BRANCH


def list_build_steps(node_id_map, icon_color=None) -> [BuildStep]:
    log.debug("Filter nodes: icon_color %s", icon_color)

    result = []
    for node in node_id_map.values():
        if node['_class'] == 'org.jenkinsci.plugins.workflow.cps.nodes.StepAtomNode':
            if icon_color is None or node['iconColor'] == icon_color:
                build_step = BuildStep(
                    node['id'],
                    node['url'],
                    node['displayName'],
                    branch_name(node_id_map, node)
                )
                result.append(build_step)

    return result


def extract_log_from_html(html):
    # Cheap and easy
    START_MARKER = '<pre class="console-output">'
    END_MARKER = "</pre>"
    pre_start = html.find(START_MARKER)
    pre_end = html[pre_start:].find(END_MARKER)
    return html[pre_start + len(START_MARKER): pre_end]


def filename_safe(s):
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    return ''.join(c if c in valid_chars else _ for c in s)


def directory_is_empty(path):
    glob_result = path.glob('*')
    try:
        item = next(glob_result)
        return False
    except StopIteration:
        return True


def main():
    args = argument_parser().parse_args()

    if args.debug:
        logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    try:
        jenkins_url = os.environ['JENKINS_URL']
    except KeyError:
        raise RuntimeError("Please set JENKINS_URL");

    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if not directory_is_empty(outdir):
        raise RuntimeError("Output directory {} is not empty.".format(outdir))

    build_info = fetch_build_info(jenkins_url, build_path(args.job, args.build))

    build_info_path = outdir.joinpath('build_info.json')
    build_info_path.write_text(json.dumps(build_info))
    log.info("Wrote %s", build_info_path)

    node_id_map = find_step_nodes(build_info)

    steps = list_build_steps(node_id_map, args.only_icon_color)
    for step in steps:
        step_html = fetch_step_html(jenkins_url, step.url)

        if step_html:
            step_basename = filename_safe(
                '.'.join([step.branch_name, step.id_str, step.display_name])
            )

            step_html_path = outdir.joinpath('{}.html'.format(step_basename))
            step_html_path.write_text(step_html)
            log.info("Wrote %s", step_html_path)

            step_log = extract_log_from_html(step_html)
            step_log_path = outdir.joinpath('{}.log'.format(step_basename))
            step_log_path.write_text(step_log)
            log.info("Wrote %s", step_log_path)


try:
    main()
except RuntimeError as e:
    sys.stderr.write("ERROR: {}\n".format(e))
    sys.exit(1)
