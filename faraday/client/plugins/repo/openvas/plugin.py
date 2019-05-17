#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Faraday Penetration Test IDE
Copyright (C) 2013  Infobyte LLC (http://www.infobytesec.com/)
See the file 'doc/LICENSE' for the license information

'''
from __future__ import with_statement
import re
import os
import sys
from collections import defaultdict

try:
    import xml.etree.cElementTree as ET
    import xml.etree.ElementTree as ET_ORIG
    ETREE_VERSION = ET_ORIG.VERSION
except ImportError:
    import xml.etree.ElementTree as ET
    ETREE_VERSION = ET.VERSION

from faraday.client.plugins import core
from faraday.client.start_client import FARADAY_BASE
from faraday.client.plugins.plugins_utils import filter_services

ETREE_VERSION = [int(i) for i in ETREE_VERSION.split(".")]

current_path = os.path.abspath(os.getcwd())

__author__ = "Francisco Amato"
__copyright__ = "Copyright (c) 2013, Infobyte LLC"
__credits__ = ["Francisco Amato"]
__license__ = ""
__version__ = "1.0.0"
__maintainer__ = "Francisco Amato"
__email__ = "famato@infobytesec.com"
__status__ = "Development"


class OpenvasXmlParser(object):
    """
    The objective of this class is to parse an xml file generated by the openvas tool.

    TODO: Handle errors.
    TODO: Test openvas output version. Handle what happens if the parser doesn't support it.
    TODO: Test cases.

    @param openvas_xml_filepath A proper xml generated by openvas
    """

    def __init__(self, xml_output):
        self.target = None
        self.port = "80"
        self.host = None
        tree = self.parse_xml(xml_output)
        if tree:
            self.hosts = self.get_hosts(tree)
            self.items = [data for data in self.get_items(tree, self.hosts)]
        else:
            self.items = []

    def parse_xml(self, xml_output):
        """
        Open and parse an xml file.

        TODO: Write custom parser to just read the nodes that we need instead of
        reading the whole file.

        @return xml_tree An xml tree instance. None if error.
        """
        try:
            tree = ET.fromstring(xml_output)
        except SyntaxError, err:
            print "SyntaxError: %s. %s" % (err, xml_output)
            return None

        return tree

    def get_items(self, tree, hosts):
        """
        @return items A list of Host instances
        """
        try:
            report = tree.findall('report')[0]
            results = report.findall('results')[0]
            for node in results.findall('result'):
                yield Item(node, hosts)

        except Exception:
            result = tree.findall('result')
            for node in result:
                yield Item(node, hosts)

    def get_hosts(self, tree):
        # Hosts are located in: /report/report/host
        # hosts_dict will contain has keys its details and its hostnames
        hosts = tree.findall('report/host')
        hosts_dict = {}
        for host in hosts:
            details = self.get_data_from_detail(host.findall('detail'))
            hosts_dict[host.find('ip').text] = details

        return hosts_dict

    def get_data_from_detail(self, details):
        data = {}
        details_data = defaultdict(list)
        hostnames = []
        for item in details:
            name = item.find('name').text
            value = item.find('value').text
            if 'EXIT' not in name:
                if name == 'hostname':
                    hostnames.append(value)
                else:
                    value = self.do_clean(value)
                    details_data[name].append(value)

        data['details'] = details_data
        data['hostnames'] = hostnames

        return data

    def do_clean(self, value):
        myreturn = ""
        if value is not None:
            myreturn = re.sub("\s+", " ", value)

        return myreturn.strip()


def get_attrib_from_subnode(xml_node, subnode_xpath_expr, attrib_name):
    """
    Finds a subnode in the item node and the retrieves a value from it

    @return An attribute value
    """
    global ETREE_VERSION
    node = None

    if ETREE_VERSION[0] <= 1 and ETREE_VERSION[1] < 3:

        match_obj = re.search(
            "([^\@]+?)\[\@([^=]*?)=\'([^\']*?)\'",
            subnode_xpath_expr)

        if match_obj is not None:
            node_to_find = match_obj.group(1)
            xpath_attrib = match_obj.group(2)
            xpath_value = match_obj.group(3)
            for node_found in xml_node.findall(node_to_find):
                if node_found.attrib[xpath_attrib] == xpath_value:
                    node = node_found
                    break
        else:
            node = xml_node.find(subnode_xpath_expr)

    else:
        node = xml_node.find(subnode_xpath_expr)

    if node is not None:
        return node.get(attrib_name)

    return None


class Item(object):
    """
    An abstract representation of a Item
    @param item_node A item_node taken from an openvas xml tree
    """

    def __init__(self, item_node, hosts):
        self.node = item_node
        self.host = self.get_text_from_subnode('host')
        self.subnet = self.get_text_from_subnode('subnet')

        if self.subnet is '':
            self.subnet = self.host

        self.port = "None"
        self.severity = self.severity_mapper()
        self.service = "Unknown"
        self.protocol = ""
        port = self.get_text_from_subnode('port')

        if "general" not in port:
            # service vuln
            info = port.split("/")
            self.port = info[0]
            self.protocol = info[1]
            host_details = hosts[self.host].get('details')
            self.service = self.get_service(port, host_details)
        else:
            # general was found in port data
            # this is a host vuln
            # this case will have item.port = 'None'
            info = port.split("/")
            self.protocol = info[1]
            self.service = info[0]  # this value is general

        self.nvt = self.node.findall('nvt')[0]
        self.node = self.nvt
        self.id = self.node.get('oid')
        self.name = self.get_text_from_subnode('name')
        self.cve = self.get_text_from_subnode(
            'cve') if self.get_text_from_subnode('cve') != "NOCVE" else ""
        self.bid = self.get_text_from_subnode(
            'bid') if self.get_text_from_subnode('bid') != "NOBID" else ""
        self.xref = self.get_text_from_subnode(
            'xref') if self.get_text_from_subnode('xref') != "NOXREF" else ""

        self.description = ''
        self.resolution = ''
        self.cvss_vector = ''
        self.tags = self.get_text_from_subnode('tags')
        if self.tags:
            tags_data = self.get_data_from_tags(self.tags)
            self.description = tags_data['description']
            self.resolution = tags_data['solution']
            self.cvss_vector = tags_data['cvss_base_vector']

    def get_text_from_subnode(self, subnode_xpath_expr):
        """
        Finds a subnode in the host node and the retrieves a value from it.

        @return An attribute value
        """
        sub_node = self.node.find(subnode_xpath_expr)
        if sub_node is not None and sub_node.text is not None:
            return sub_node.text.strip()

        return ''

    def severity_mapper(self):
        severity = self.get_text_from_subnode('threat')
        if severity == 'Alarm':
            severity = 'Critical'
        return severity

    def get_service(self, port, details_from_host):
        # details_from_host:
        # name: name of detail
        # value: list with the values associated with the name
        for name, value in details_from_host.items():
            service_detail = self.get_service_from_details(name, value, port)

            if service_detail:
                return service_detail

        # if the service is not in details_from_host, we will search it in
        # the file port_mapper.txt
        srv = filter_services()
        for service in srv:
            if service[0] == port:
                return service[1]

        return "Unknown"

    def do_clean(self, value):
        myreturn = ""
        if value is not None:
            myreturn = re.sub("\s+", " ", value)

        return myreturn.strip()

    def get_service_from_details(self, name, value_list, port):
        # detail:
        # name: name of detail
        # value_list: list with the values associated with the name
        res = None
        priority = 0

        for value in value_list:
            if name == 'Services':
                aux_port = port.split('/')[0]
                value_splited = value.split(',')
                if value_splited[0] == aux_port:
                    res = value_splited[2]
                    priority = 3

            elif '/' in value and priority != 3:
                auxiliar_value = value.split('/')[0]
                if auxiliar_value == port.split('/')[0]:
                    res = name
                    priority = 2

            elif value.isdigit() and priority == 0:
                if value == port.split('/')[0]:
                    res = name
                    priority = 1

            elif '::' in value and priority == 0:
                aux_value = value.split('::')[0]
                auxiliar_port = port.split('/')[0]
                if aux_value == auxiliar_port:
                    res = name

        return res

    def get_data_from_tags(self, tags_text):
        clean_text = self.do_clean(tags_text)
        tags = clean_text.split('|')
        summary = ''
        insight = ''
        data = {
            'solution': '',
            'cvss_base_vector': '',
            'description': ''
        }
        for tag in tags:
            splited_tag = tag.split('=', 1)
            if splited_tag[0] in data.keys():
                data[splited_tag[0]] = splited_tag[1]
            elif splited_tag[0] == 'summary':
                summary = splited_tag[1]
            elif splited_tag[0] == 'insight':
                insight = splited_tag[1]

        data['description'] = ' '.join([summary, insight]).strip()

        return data


class OpenvasPlugin(core.PluginBase):
    """
    Example plugin to parse openvas output.
    """

    def __init__(self):
        core.PluginBase.__init__(self)
        self.id = "Openvas"
        self.name = "Openvas XML Output Plugin"
        self.plugin_version = "0.3"
        self.version = "9.0.3"
        self.framework_version = "1.0.0"
        self.options = None
        self._current_output = None
        self.target = None
        self._command_regex = re.compile(
            r'^(openvas|sudo openvas|\.\/openvas).*?')

        global current_path
        self._output_file_path = os.path.join(self.data_path,
                                              "openvas_output-%s.xml" % self._rid)

    def parseOutputString(self, output, debug=False):
        """
        This method will discard the output the shell sends, it will read it
        from the xml where it expects it to be present.

        NOTE: if 'debug' is true then it is being run from a test case and the
        output being sent is valid.
        """

        parser = OpenvasXmlParser(output)

        web = False
        ids = {}
        # The following threats values will not be taken as vulns
        self.ignored_severities = ['Log', 'Debug']

        for ip, values in parser.hosts.items():
            # values contains: ip details and ip hostnames
            h_id = self.createAndAddHost(
                ip,
                hostnames=values['hostnames']
            )
            ids[ip] = h_id

        for item in parser.items:
            if item.name is not None:
                ref = []
                if item.cve:
                    ref.append(item.cve.encode("utf-8"))
                if item.bid:
                    ref.append(item.bid.encode("utf-8"))
                if item.xref:
                    ref.append(item.xref.encode("utf-8"))
                if item.tags and item.cvss_vector:
                    ref.append(item.cvss_vector.encode("utf-8"))

                if item.subnet in ids:
                    h_id = ids[item.host]
                else:
                    h_id = self.createAndAddHost(
                        item.subnet,
                        hostnames=[item.host])
                    ids[item.subnet] = h_id

                if item.port == "None":
                    if item.severity not in self.ignored_severities:
                        v_id = self.createAndAddVulnToHost(
                            h_id,
                            item.name.encode("utf-8"),
                            desc=item.description.encode("utf-8"),
                            severity=item.severity.encode("utf-8"),
                            resolution=item.resolution.encode("utf-8"),
                            ref=ref)
                else:
                    if item.service:
                        web = True if re.search(
                            r'^(www|http)',
                            item.service) else False
                    else:
                        web = True if item.port in ('80', '443', '8080') else False

                    if item.subnet + "_" + item.port in ids:
                        s_id = ids[item.subnet + "_" + item.port]
                    else:
                        s_id = self.createAndAddServiceToHost(
                            h_id,
                            item.service,
                            item.protocol,
                            ports=[str(item.port)]
                        )
                        ids[item.subnet + "_" + item.port] = s_id
                    if web:
                        if item.severity not in self.ignored_severities:
                            v_id = self.createAndAddVulnWebToService(
                                h_id,
                                s_id,
                                item.name.encode("utf-8"),
                                desc=item.description.encode("utf-8"),
                                website=item.host,
                                severity=item.severity.encode("utf-8"),
                                ref=ref,
                                resolution=item.resolution.encode("utf-8"))
                    elif item.severity not in self.ignored_severities:
                        self.createAndAddVulnToService(
                            h_id,
                            s_id,
                            item.name.encode("utf-8"),
                            desc=item.description.encode("utf-8"),
                            severity=item.severity.encode("utf-8"),
                            ref=ref,
                            resolution=item.resolution.encode("utf-8"))

        del parser

    def _isIPV4(self, ip):
        if len(ip.split(".")) == 4:
            return True
        else:
            return False

    def processCommandString(self, username, current_path, command_string):
        return None

    def setHost(self):
        pass


def createPlugin():
    return OpenvasPlugin()

if __name__ == '__main__':
    parser = OpenvasPlugin()
    with open("/home/javier/7_faraday_Openvas.xml","r") as report:
        parser.parseOutputString(report.read())
        #for item in parser.items:
            #if item.status == 'up':
                #print item