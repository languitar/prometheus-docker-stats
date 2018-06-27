#!/usr/bin/env python2

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import sys
import time

from docker import Client
import six

DOCKER_CLIENT = Client(
    base_url=os.environ.get('DOCKER_CLIENT_URL', 'unix://var/run/docker.sock'))


def get_metrics():
    stats = get_container_stats()
    metrics = {}
    for container_name, container_stats in six.iteritems(stats):
        metrics[str(container_name)] = json.loads(container_stats.next())
    return parse_api_metrics(metrics)


def parse_api_metrics(m):
    lines = []
    for container, stats in six.iteritems(m or {}):
        lines.append(make_line('last_seen', container, 1))
        cpu_stats = stats.get('cpu_stats', {})
        lines.append(
            make_line('system_cpu_usage', container,
                      cpu_stats['system_cpu_usage']))
        for stat_name in cpu_stats.get('cpu_usage'):
            try:
                lines.append(
                    make_line('cpu_usage_%s' % stat_name, container,
                              cpu_stats['cpu_usage'][stat_name]))
            except TypeError:
                pass
        memory_stats = stats.get('memory_stats')
        for stat_name in memory_stats:
            if stat_name != 'stats':
                lines.append(
                    make_line('memory_stats_%s' % stat_name, container,
                              memory_stats[stat_name]))
        for stat_name in memory_stats.get('stats'):
            lines.append(
                make_line('memory_stats_%s' % stat_name, container,
                          memory_stats['stats'][stat_name]))
        io_stats = stats.get('blkio_stats',
                             {}).get('io_service_bytes_recursive')
        io_stats_dict = {i.get('op'): i.get('value') for i in io_stats}
        for stat_name, stat_value in six.iteritems(io_stats_dict):
            lines.append(
                make_line('blkio_stats_io_service_bytes_%s' % stat_name.lower(),
                          container, stat_value))
        network_stats = stats.get('networks')
        for stat_name, interface_stats in six.iteritems(network_stats or {}):
            for metric_name, metric_value in six.iteritems(
                            interface_stats or {}):
                lines.append(
                    make_line('networks_%s' % metric_name,
                              container, metric_value,
                              {'interface': stat_name}))
    lines.sort()
    string_buffer = "\n".join(lines)
    string_buffer += "\n"
    return string_buffer


def make_line(metric_name, container, metric, tags=None):
    real_tags = {
        'container': container,
    }
    if tags:
        real_tags.update(tags)
    tag_line = ','.join(['%s="%s"' % (k, v) for k, v in real_tags.iteritems()])
    metric_name = metric_name.replace('.', '_').replace('-', '_').lower()
    return str('docker_stats_%s{%s} %s' % (metric_name, tag_line, int(metric)))


def get_container_stats():
    stats_dict = {}
    running_containers = DOCKER_CLIENT.containers()
    for container in running_containers:
        container_name = container['Names'][0].lstrip('/')
        if not stats_dict.get(container_name):
            stats_dict.update(
                {
                    container_name: DOCKER_CLIENT.stats(
                        container=container['Id'], stream=True)
                }
            )
    return stats_dict


def parse_line_value(default_k, k, v, container):
    k = '{}_{}'.format(default_k, k) if default_k not in k else k
    lines = []
    if isinstance(v, list):
        for i, item in enumerate(v):
            if re.match(r'^[A-Za-z_]+\s[0-9]+$', item):
                key, value = item.split(' ')
                lines.append(
                    make_line('{}_{}'.format(k, key), container, value))
            elif re.match(r'^[0-9]+:[0-9]+\s[A-Za-z_]+\s[0-9]+', item):
                _, key, value = item.split(' ')
                lines.append(
                    make_line('{}_{}'.format(k, key), container, value))
            elif re.match('^[0-9]+$', item):
                if len(v) > 1:
                    lines.append(
                        make_line('{}_{}'.format(k, i), container, item))
                else:
                    lines.append(make_line(k, container, item))
    else:
        lines.append(make_line(k, container, v))
    return lines


class MetricsHandler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        if self.path not in ['/metrics', '/metrics/']:
            self.send_response(404)
            self.end_headers()
            return

        try:
            metrics = get_metrics()

            self._set_headers()
            self.wfile.write(metrics)
        except Exception, e:
            import traceback
            self.send_error(500, str(e) + '\n\n' + traceback.format_exc())

    def do_HEAD(self):
        self._set_headers()


def run(server_class=HTTPServer, handler_class=MetricsHandler, port=80):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()


if __name__ == '__main__':
    if len(sys.argv) == 2:
        run(port=int(sys.argv[1]))
    else:
        run()
