#!/usr/bin/env python3
import requests
import json
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
import sys
import os
import getpass
import csv
from typing import Dict, List, Tuple, Optional, Any
from requests.cookies import RequestsCookieJar
import re

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)  # type: ignore

class ACIHealthChecker:
    """Main class for ACI Health Check operations"""
    
    def __init__(self):
        self.console = Console()
        
        # Configuration with default values
        self.DEFAULT_APIC_IP = "10.8.254.91"
        self.DEFAULT_USERNAME = "admin"
        self.DEFAULT_PASSWORD = "Master082025"
        self.DEFAULT_HEALTH_THRESHOLD = 90
        self.DEFAULT_CPU_MEM_THRESHOLD = 75  # percent
        self.DEFAULT_INTERFACE_ERROR_THRESHOLD = 0
        
        self.apic_ip = ""
        self.cookies = None

    # -------------------- Authentication -------------------- #

    def get_credentials(self) -> Tuple[str, str, str]:
        """Get APIC credentials from interactive input"""
        # Get APIC IP
        try:
            apic_ip = input("Enter APIC IP (e.g., 10.10.10.1): ").strip()
        except EOFError:
            apic_ip = ""
        if not apic_ip:
            apic_ip = self.DEFAULT_APIC_IP
            self.console.print(f"[dim]Using default APIC IP: {self.DEFAULT_APIC_IP}[/dim]")

        # Get username
        try:
            username = input("Enter Username: ").strip()
        except EOFError:
            username = ""
        if not username:
            username = self.DEFAULT_USERNAME
            self.console.print(f"[dim]Using default username: {self.DEFAULT_USERNAME}[/dim]")

        # Get password
        try:
            password = getpass.getpass("Enter Password: ")
        except Exception:
            password = ""
        if not password:
            password = self.DEFAULT_PASSWORD
            self.console.print(f"[dim]Using default password: {self.DEFAULT_PASSWORD}[/dim]")

        return apic_ip, username, password

    def apic_login(self, apic_ip: str, username: str, password: str) -> Optional[RequestsCookieJar]:
        """Authenticate to APIC and return session cookies"""
        login_url = f"https://{apic_ip}/api/aaaLogin.json"
        auth_payload = {"aaaUser": {"attributes": {"name": username, "pwd": password}}}

        try:
            resp = requests.post(login_url, json=auth_payload, verify=False, timeout=30)
            if resp.status_code != 200:
                self.console.print(f"[red]✗ Login failed with status code: {resp.status_code}[/red]")
                return None

            # Check if login was successful
            response_data = resp.json()
            if 'imdata' in response_data and len(response_data['imdata']) > 0:
                if isinstance(response_data['imdata'][0], dict) and 'error' in response_data['imdata'][0]:
                    self.console.print("[red]✗ Authentication failed: Invalid credentials[/red]")
                    return None

            self.console.print(f"[green]✓ Successfully authenticated to APIC {apic_ip}[/green]")
            return resp.cookies
        except requests.exceptions.ConnectionError:
            self.console.print(f"[red]✗ Cannot connect to APIC at {apic_ip}[/red]")
            return None
        except requests.exceptions.Timeout:
            self.console.print("[red]✗ Connection timeout[/red]")
            return None
        except Exception as e:
            self.console.print(f"[red]✗ Login failed: {str(e)}[/red]")
            return None

    # -------------------- API Client -------------------- #

    class APIClient:
        """Handles API communication with APIC"""
        
        def __init__(self, apic_ip: str, cookies: RequestsCookieJar, console: Console):
            self.apic_ip = apic_ip
            self.cookies = cookies
            self.console = console

        def fetch_api(self, url: str, description: str = "Fetching data") -> Optional[Dict]:
            """Generic API fetch function with error handling"""
            try:
                with self.console.status(f"[cyan]{description}...[/cyan]", spinner="dots"):
                    response = requests.get(url, cookies=self.cookies, verify=False, timeout=60)

                if response.status_code != 200:
                    self.console.print(f"[yellow]⚠ API call to {url} returned status {response.status_code}[/yellow]")
                    return None

                return response.json()
            except requests.exceptions.Timeout:
                self.console.print(f"[yellow]⚠ Timeout while {description}[/yellow]")
                return None
            except Exception as e:
                self.console.print(f"[yellow]⚠ Error while {description}: {str(e)}[/yellow]")
                return None

        def fetch_apic_health(self) -> Optional[Dict]:
            """Fetch APIC cluster health data"""
            url = f"https://{self.apic_ip}/api/node/mo/topology/pod-1/node-1.json?query-target=subtree&target-subtree-class=infraWiNode"
            return self.fetch_api(url, "Fetching APIC health")

        def fetch_top_system(self) -> Optional[Dict]:
            """Fetch topSystem data with health information"""
            url = f"https://{self.apic_ip}/api/node/class/topSystem.json?rsp-subtree-include=health"
            return self.fetch_api(url, "Fetching node information")

        def fetch_faults(self, hours_back: int = 20) -> Optional[Dict]:
            """Fetch fault information from the last specified hours"""
            # Calculate the time filter (in ACI's time format)
            from datetime import datetime, timedelta
            time_threshold = datetime.now() - timedelta(hours=hours_back)
            # ACI uses ISO format with milliseconds: 2024-01-15T10:30:00.000Z
            time_filter = time_threshold.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            # Filter for faults created or changed in the last specified hours
            url = f"https://{self.apic_ip}/api/node/class/faultInst.json?query-target-filter=and(gt(faultInst.created,\"{time_filter}\"),or(w(severity,\"critical\"),w(severity,\"major\")))"
            
            return self.fetch_api(url, f"Fetching faults from last {hours_back} hours")

        def fetch_cpu_mem(self) -> Tuple[Optional[Dict], Optional[Dict]]:
            """Fetch CPU and memory utilization data"""
            cpu_url = f"https://{self.apic_ip}/api/node/class/procSysCPU1d.json"
            mem_url = f"https://{self.apic_ip}/api/node/class/procSysMem1d.json"

            cpu_data = self.fetch_api(cpu_url, "Fetching CPU data")
            mem_data = self.fetch_api(mem_url, "Fetching memory data")

            return cpu_data, mem_data

        def fetch_fabric_health(self) -> Optional[Dict]:
            """Fetch fabric health data"""
            url = f"https://{self.apic_ip}/api/node/class/fabricHealthTotal.json"
            return self.fetch_api(url, "Fetching fabric health")

        def fetch_crc_errors(self) -> Optional[Dict]:
            """Fetch CRC error statistics from rmonEtherStats"""
            url = f"https://{self.apic_ip}/api/node/class/rmonEtherStats.json"
            return self.fetch_api(url, "Fetching CRC error statistics")

        def fetch_fcs_errors(self) -> Optional[Dict]:
            """Fetch FCS error statistics from rmonDot3Stats"""
            url = f"https://{self.apic_ip}/api/node/class/rmonDot3Stats.json"
            return self.fetch_api(url, "Fetching FCS error statistics")

        def fetch_drop_errors(self) -> List[Dict]:
            """Get drop error statistics from rmonEgrCounters"""
            url = f"https://{self.apic_ip}/api/node/class/rmonEgrCounters.json"
            data = self.fetch_api(url, "Fetching drop errors")
            return data.get("imdata", []) if data else []

        def fetch_output_errors(self) -> List[Dict]:
            """Get output error statistics from rmonIfOut"""
            url = f"https://{self.apic_ip}/api/node/class/rmonIfOut.json"
            data = self.fetch_api(url, "Fetching output errors")
            return data.get("imdata", []) if data else []

    # -------------------- Data Processors -------------------- #

    class DataProcessor:
        """Processes raw APIC data into structured formats"""
        
        @staticmethod
        def _get_first_child_attributes(item: Dict, child_key: str) -> Dict:
            """Helper to find a child entry by class name and return its attributes, if any."""
            children = item.get(list(item.keys())[0], {}).get("children", []) if isinstance(item, dict) else []
            for c in children:
                if child_key in c:
                    return c[child_key].get("attributes", {})
            return {}

        @staticmethod
        def process_apic_data(data: Dict) -> List[Dict]:
            """Process APIC controller data (robust to different APIC JSON shapes)"""
            nodes = []
            if not data:
                return nodes

            # If data has a top-level list keyed by 'infraWiNode' (some endpoints), handle it
            if isinstance(data, dict) and "infraWiNode" in data and isinstance(data["infraWiNode"], list):
                for node in data["infraWiNode"]:
                    attrs = node.get("attributes", {}) if isinstance(node, dict) else {}
                    name = attrs.get("nodeName") or attrs.get("name") or attrs.get("id", "")
                    serial = attrs.get("mbSn") or attrs.get("serial", "")
                    nodes.append({
                        "name": name,
                        "serial": serial,
                        "mode": attrs.get("apicMode", ""),
                        "status": attrs.get("operSt", ""),
                        "health_str": attrs.get("health", "unknown"),
                        "health": 100 if str(attrs.get("health", "")).lower() in ["fully-fit", "100"] else 50 if str(attrs.get("health", "")).lower() == "degraded" else int(attrs.get("health", 0) or 0)
                    })
                return nodes

            # More common APIC responses use 'imdata' list
            imdata = data.get("imdata") if isinstance(data, dict) else None
            if not imdata:
                return nodes

            for entry in imdata:
                if not isinstance(entry, dict):
                    continue
                # entry will have a single key whose value contains attributes
                class_key = next(iter(entry.keys()), None)
                if not class_key:
                    continue
                obj = entry.get(class_key, {})
                attrs = obj.get("attributes", {})
                # Try to form sensible fields even if names differ
                name = attrs.get("nodeName") or attrs.get("name") or attrs.get("id") or ""
                serial = attrs.get("mbSn") or attrs.get("serial") or ""
                # ip may be stored in different fields
                ip = attrs.get("oobNetwork", {}).get("address4", "").split("/")[0] if isinstance(attrs.get("oobNetwork"), dict) else attrs.get("oobMgmtAddr", "") or attrs.get("address", "")
                # health string may be nested or numeric
                health_str = attrs.get("health") or attrs.get("healthRollup") or ""
                # derive numeric health
                try:
                    numeric_health = int(attrs.get("health", attrs.get("cur", 0)) or 0)
                except Exception:
                    numeric_health = 100 if str(health_str).lower() in ["fully-fit", "fully fit"] else 50 if str(health_str).lower() == "degraded" else 0

                nodes.append({
                    "name": name,
                    "serial": serial,
                    "ip": ip,
                    "mode": attrs.get("apicMode", ""),
                    "status": attrs.get("operSt", attrs.get("status", "")),
                    "health_str": health_str if health_str else str(numeric_health),
                    "health": numeric_health
                })
            return nodes

        @staticmethod
        def process_leaf_spine(top_data: Dict, cpu_data: Dict, mem_data: Dict) -> List[Dict]:
            """Process leaf and spine node data"""
            nodes = []

            if not top_data or "imdata" not in top_data:
                return nodes

            # Build CPU/Memory map keyed by node-id forms ('1', 'node-1')
            cpu_map: Dict[str, float] = {}
            mem_map: Dict[str, float] = {}

            if cpu_data and "imdata" in cpu_data:
                for c in cpu_data.get("imdata", []):
                    obj_key = next(iter(c.keys()), None)
                    if not obj_key or obj_key not in c:
                        continue
                    attrs = c[obj_key].get("attributes", {})
                    dn = attrs.get("dn", "")
                    # try to extract node id
                    node_id_numeric = None
                    m = re.search(r'node-(\d+)', dn)
                    if m:
                        node_id_numeric = m.group(1)
                    else:
                        # alternative parsing of dn e.g. something like sys/proc/syscpu
                        parts = dn.split("/")
                        for p in parts:
                            pm = re.match(r'node-(\d+)', p)
                            if pm:
                                node_id_numeric = pm.group(1)
                                break

                    try:
                        user_util = float(attrs.get("userAvg", 0))
                        kernel_util = float(attrs.get("kernelAvg", 0))
                        primary_util = user_util + kernel_util
                    except Exception:
                        primary_util = float(attrs.get("util", 0) or 0)

                    # if we got a node id, store both keyed forms
                    if node_id_numeric is not None:
                        cpu_map[node_id_numeric] = primary_util
                        cpu_map[f"node-{node_id_numeric}"] = primary_util

            if mem_data and "imdata" in mem_data:
                for m in mem_data.get("imdata", []):
                    obj_key = next(iter(m.keys()), None)
                    if not obj_key or obj_key not in m:
                        continue
                    attrs = m[obj_key].get("attributes", {})
                    dn = attrs.get("dn", "")
                    node_id_numeric = None
                    mm = re.search(r'node-(\d+)', dn)
                    if mm:
                        node_id_numeric = mm.group(1)

                    if "PercUsedMemoryAvg" in attrs:
                        try:
                            mem_val = float(attrs.get("PercUsedMemoryAvg", 0))
                        except Exception:
                            mem_val = 0.0
                    else:
                        try:
                            total_avg = float(attrs.get("totalAvg", 0))
                            used_avg = float(attrs.get("usedAvg", 0))
                            mem_val = (used_avg / total_avg) * 100 if total_avg > 0 else 0.0
                        except Exception:
                            mem_val = 0.0

                    if node_id_numeric is not None:
                        mem_map[node_id_numeric] = mem_val
                        mem_map[f"node-{node_id_numeric}"] = mem_val

            # Now parse topSystem entries
            for item in top_data.get("imdata", []):
                class_key = next(iter(item.keys()), None)
                if not class_key:
                    continue
                top_obj = item[class_key]
                attr = top_obj.get("attributes", {})
                role = (attr.get("role") or "").lower()
                if role not in ["leaf", "spine"]:
                    # Some environments don't set role; we can still include switches by checking other hints
                    # skip if role missing to avoid extraneous entries
                    continue

                # Find health child attributes if present
                health_attr = {}
                for child in top_obj.get("children", []):
                    if "healthInst" in child:
                        health_attr = child["healthInst"].get("attributes", {})
                        break
                    # also check nested child's children
                    for cc in child.get("children", []):
                        if "healthInst" in cc:
                            health_attr = cc["healthInst"].get("attributes", {})
                            break

                # health score numeric
                try:
                    health_score = int(health_attr.get("cur", attr.get("health", 0) or 0))
                except Exception:
                    try:
                        health_score = int(attr.get("health", 0) or 0)
                    except Exception:
                        health_score = 0

                # node id detection: prefer id attribute
                node_id = str(attr.get("id") or attr.get("serial") or "")
                # if id looks like numeric, keep numeric only to match cpu_map keys
                if node_id.startswith("node-"):
                    node_id_key = node_id.replace("node-", "")
                else:
                    node_id_key = node_id

                # fallback: try to extract from oobMgmtAddr or dn fields if id not present
                if not node_id_key:
                    dn = attr.get("dn", "")
                    m = re.search(r'node-(\d+)', dn)
                    if m:
                        node_id_key = m.group(1)

                nodes.append({
                    "name": attr.get("name", ""),
                    "role": role,
                    "serial": attr.get("serial", ""),
                    "ip": attr.get("oobMgmtAddr", attr.get("address", "")),
                    "version": attr.get("version", ""),
                    "uptime": attr.get("systemUpTime", ""),
                    "health": health_score,
                    "cpu": float(cpu_map.get(node_id_key, 0)),
                    "memory": float(mem_map.get(node_id_key, 0))
                })
            return nodes

        @staticmethod
        def process_faults(data: Dict, hours_back: int = 20) -> List[Dict]:
            """Process fault data from the last specified hours"""
            faults = []
            if not data or "imdata" not in data:
                return faults

            # Calculate time threshold for additional filtering
            from datetime import datetime, timedelta
            time_threshold = datetime.now() - timedelta(hours=hours_back)

            for f in data.get("imdata", []):
                class_key = next(iter(f.keys()), None)
                if not class_key:
                    continue
                attr = f[class_key].get("attributes", {})
                
                # Only include critical and major faults
                if attr.get("severity", "").lower() in ["critical", "major"]:
                    # Parse the last transition time for additional filtering
                    last_change_str = attr.get("lastTransition", "")
                    if last_change_str:
                        try:
                            # Parse ACI timestamp format: 2024-01-15T10:30:00.000Z
                            last_change = datetime.strptime(last_change_str.split('.')[0], "%Y-%m-%dT%H:%M:%S")
                            # If the fault is older than our threshold, skip it
                            if last_change < time_threshold:
                                continue
                        except (ValueError, IndexError):
                            # If we can't parse the timestamp, include the fault to be safe
                            pass
                    
                    faults.append({
                        "severity": attr.get("severity", ""),
                        "code": attr.get("code", ""),
                        "description": attr.get("descr", ""),
                        "last_change": attr.get("lastTransition", ""),
                        "dn": attr.get("dn", "")
                    })
            return faults

        @staticmethod
        def process_fabric_health(data: Dict) -> int:
            """Extract fabric health score from fabricHealthTotal data"""
            if not data or "imdata" not in data or not data["imdata"]:
                return 0

            # pick first item that has fabricHealthTotal
            for item in data.get("imdata", []):
                key = next(iter(item.keys()), None)
                if key and "fabricHealthTotal" in key:
                    health_attr = item[key].get("attributes", {})
                    try:
                        return int(health_attr.get("cur", 0))
                    except Exception:
                        return 0

            # fallback
            try:
                health_attr = data["imdata"][0][next(iter(data["imdata"][0].keys()))].get("attributes", {})
                return int(health_attr.get("cur", 0) or 0)
            except Exception:
                return 0

        @staticmethod
        def process_fcs_errors(data: Dict, threshold: int) -> List[Dict]:
            """Process FCS error data"""
            return ACIHealthChecker.DataProcessor._process_interface_errors(
                data, threshold, "fCSErrors", "fcsErrors", "fcs_errors"
            )

        @staticmethod
        def process_crc_errors(data: Dict, threshold: int) -> List[Dict]:
            """Process CRC error data"""
            return ACIHealthChecker.DataProcessor._process_interface_errors(
                data, threshold, "cRCAlignErrors", "crcAlignErrors", "crc_errors"
            )

        @staticmethod
        def process_drop_errors(data: Dict, threshold: int) -> List[Dict]:
            """Process Drop error data"""
            return ACIHealthChecker.DataProcessor._process_interface_errors(
                data, threshold, "dropPkts", "dropPkts", "drop_errors"
            )

        @staticmethod
        def process_output_errors(data: Dict, threshold: int) -> List[Dict]:
            """Process Output error data"""
            return ACIHealthChecker.DataProcessor._process_interface_errors(
                data, threshold, "outErrors", "outErrors", "output_errors"
            )

        @staticmethod
        def _process_interface_errors(data: Dict, threshold: int, 
                                    primary_key: str, secondary_key: str, 
                                    error_field: str) -> List[Dict]:
            """Generic interface error processor"""
            interfaces = []
            if not data or "imdata" not in data:
                return interfaces

            for item in data.get("imdata", []):
                class_key = next(iter(item.keys()), None)
                if not class_key:
                    continue
                attr = item[class_key].get("attributes", {})

                # Get errors (key names differ by schema)
                errors = int(attr.get(primary_key, attr.get(secondary_key, 0) or 0))

                if errors > threshold:
                    dn = attr.get("dn", "")
                    interface_name = "Unknown"
                    node_id = "Unknown"

                    interface_match = re.search(r'(phys|aggr)-\[(.*?)\]', dn)
                    if interface_match:
                        interface_name = interface_match.group(2)

                    node_match = re.search(r'node-(\d+)', dn)
                    if node_match:
                        node_id = f"node-{node_match.group(1)}"

                    interfaces.append({
                        "node": node_id,
                        "interface": interface_name,
                        error_field: errors,
                        "dn": dn
                    })

            return interfaces

    # -------------------- Report Generators -------------------- #

    class ReportGenerator:
        """Handles report generation and display"""
        
        def __init__(self, console: Console, health_threshold: int, 
                     cpu_mem_threshold: int, interface_threshold: int):
            self.console = console
            self.health_threshold = health_threshold
            self.cpu_mem_threshold = cpu_mem_threshold
            self.interface_threshold = interface_threshold

        def print_report(self, apic_nodes: List[Dict], leaf_spine_nodes: List[Dict],
                        faults: List[Dict], fabric_health: int, fcs_errors: List[Dict],
                        crc_errors: List[Dict], drop_errors: List[Dict], output_errors: List[Dict]):
            """Print comprehensive health report"""

            # Fabric health panel
            health_status = "Normal" if fabric_health >= self.health_threshold else "Needs Attention"
            status_color = "green" if fabric_health >= self.health_threshold else "red"

            self.console.print(Panel(
                f"Fabric Health Score: [bold]{fabric_health}%[/bold] - [{status_color}]{health_status}[/{status_color}]",
                title="FABRIC HEALTH SUMMARY",
                expand=False
            ))
            self.console.print()

            # APIC Table
            self._print_apic_table(apic_nodes)
            
            # Leaf/Spine Table
            self._print_leaf_spine_table(leaf_spine_nodes)
            
            # Faults Table
            self._print_faults_table(faults)
            
            # Error Tables
            self._print_error_table(fcs_errors, "FCS", "fcs_errors")
            self._print_error_table(crc_errors, "CRC", "crc_errors")
            self._print_error_table(drop_errors, "Drop", "drop_errors")
            self._print_error_table(output_errors, "Output", "output_errors")

            # Generate and display summary
            summary_data = self.generate_summary(apic_nodes, leaf_spine_nodes, faults,
                                                fabric_health, fcs_errors, crc_errors, 
                                                drop_errors, output_errors)
            self.print_summary(summary_data)

        def _print_apic_table(self, apic_nodes: List[Dict]):
            """Print APIC controllers table"""
            if apic_nodes:
                apic_table = Table(title="APIC CONTROLLERS", box=box.ROUNDED)
                apic_table.add_column("Hostname", style="bold")
                apic_table.add_column("Serial")
                apic_table.add_column("Mode")
                apic_table.add_column("Status")
                apic_table.add_column("Health")

                for n in apic_nodes:
                    status_style = "green" if n.get("health", 0) >= self.health_threshold else "red"
                    apic_table.add_row(
                        str(n.get("name", "")),
                        str(n.get("serial", "")),
                        str(n.get("mode", "")),
                        str(n.get("status", "")),
                        f"[{status_style}]{n.get('health_str', '')}[/{status_style}]"
                    )
                self.console.print(apic_table)
                self.console.print()
            else:
                self.console.print("[yellow]No APIC controller data available[/yellow]")
                self.console.print()

        def _print_leaf_spine_table(self, leaf_spine_nodes: List[Dict]):
            """Print leaf/spine nodes table"""
            if leaf_spine_nodes:
                leaf_table = Table(title="LEAF/SPINE NODES", box=box.ROUNDED)
                for col in ["Hostname", "Role", "Serial", "IP", "Version", "Uptime", "Health", "CPU", "Memory"]:
                    leaf_table.add_column(col)

                for n in leaf_spine_nodes:
                    health_style = "green" if n.get("health", 0) >= self.health_threshold else "red"
                    cpu_style = "green" if n.get("cpu", 0) < self.cpu_mem_threshold else "red"
                    mem_style = "green" if n.get("memory", 0) < self.cpu_mem_threshold else "red"

                    leaf_table.add_row(
                        str(n.get("name", "")),
                        str(n.get("role", "")).capitalize(),
                        str(n.get("serial", "")),
                        str(n.get("ip", "")),
                        str(n.get("version", "")),
                        str(n.get("uptime", "")),
                        f"[{health_style}]{n.get('health', 0)}%[/{health_style}]",
                        f"[{cpu_style}]{n.get('cpu', 0):.1f}%[/{cpu_style}]",
                        f"[{mem_style}]{n.get('memory', 0):.1f}%[/{mem_style}]"
                    )
                self.console.print(leaf_table)
                self.console.print()
            else:
                self.console.print("[yellow]No leaf/spine node data available[/yellow]")
                self.console.print()

        def _print_faults_table(self, faults: List[Dict]):
            """Print faults table"""
            if faults:
                fault_table = Table(title="CRITICAL/MAJOR FAULTS", box=box.ROUNDED)
                for col in ["Severity", "Code", "Description", "Last Change", "DN"]:
                    fault_table.add_column(col)

                for f in faults:
                    severity_style = "red" if f.get("severity", "").lower() == "critical" else "yellow"
                    fault_table.add_row(
                        f"[{severity_style}]{f.get('severity', '').upper()}[/{severity_style}]",
                        str(f.get("code", "")),
                        str(f.get("description", "")),
                        str(f.get("last_change", "")),
                        str(f.get("dn", ""))
                    )
                self.console.print(fault_table)
                self.console.print()
            else:
                self.console.print(Panel("✓ No critical or major faults found", style="green"))
                self.console.print()

        def _print_error_table(self, errors: List[Dict], error_type: str, error_field: str):
            """Print error table for specific error type"""
            if errors:
                table = Table(title=f"{error_type.upper()} ERRORS (Threshold: {self.interface_threshold})", box=box.ROUNDED)
                table.add_column("Node")
                table.add_column("Interface")
                table.add_column(f"{error_type.upper()} Errors")
                table.add_column("DN")

                for intf in errors:
                    error_style = "red" if intf.get(error_field, 0) > self.interface_threshold else "yellow"
                    table.add_row(
                        str(intf.get("node", "")),
                        str(intf.get("interface", "")),
                        f"[{error_style}]{intf.get(error_field, 0)}[/{error_style}]",
                        str(intf.get("dn", ""))
                    )
                self.console.print(table)
                self.console.print()
            else:
                self.console.print(Panel(f"✓ No {error_type} errors above threshold found", style="green"))
                self.console.print()

        def generate_summary(self, apic_nodes: List[Dict], leaf_spine_nodes: List[Dict],
                            faults: List[Dict], fabric_health: int, fcs_errors: List[Dict],
                            crc_errors: List[Dict], drop_errors: List[Dict], output_errors: List[Dict]) -> Dict:
            """Generate summary data for the report"""
            # APIC Health
            apic_health_ok = all(n.get("health", 0) >= self.health_threshold for n in apic_nodes) if apic_nodes else False
            apic_count = len(apic_nodes)
            apic_problem_count = len([n for n in apic_nodes if n.get("health", 0) < self.health_threshold])

            # Leaf/Spine Health
            leaf_spine_health_ok = all(n.get("health", 0) >= self.health_threshold for n in leaf_spine_nodes) if leaf_spine_nodes else False
            leaf_spine_count = len(leaf_spine_nodes)
            leaf_spine_health_problem_count = len([n for n in leaf_spine_nodes if n.get("health", 0) < self.health_threshold])

            # CPU/Memory Health
            cpu_mem_ok = all(
                n.get("cpu", 0) < self.cpu_mem_threshold and n.get("memory", 0) < self.cpu_mem_threshold
                for n in leaf_spine_nodes
            ) if leaf_spine_nodes else False
            cpu_problem_count = len([n for n in leaf_spine_nodes if n.get("cpu", 0) >= self.cpu_mem_threshold])
            mem_problem_count = len([n for n in leaf_spine_nodes if n.get("memory", 0) >= self.cpu_mem_threshold])

            # Fabric Health
            fabric_health_ok = fabric_health >= self.health_threshold

            # Faults
            critical_faults = len([f for f in faults if f.get("severity", "").lower() == "critical"])
            major_faults = len([f for f in faults if f.get("severity", "").lower() == "major"])

            # Error counts
            fcs_error_count = len(fcs_errors or [])
            crc_error_count = len(crc_errors or [])
            drop_error_count = len(drop_errors or [])
            output_error_count = len(output_errors or [])

            # Overall status
            overall_ok = (apic_health_ok and leaf_spine_health_ok and cpu_mem_ok and
                        fabric_health_ok and critical_faults == 0 and major_faults == 0 and
                        crc_error_count == 0 and fcs_error_count == 0 and 
                        drop_error_count == 0 and output_error_count == 0)

            return {
                "overall_status": "PASS" if overall_ok else "FAIL",
                "apic": {
                    "status": "PASS" if apic_health_ok else "FAIL",
                    "total": apic_count,
                    "problems": apic_problem_count
                },
                "leaf_spine": {
                    "status": "PASS" if leaf_spine_health_ok else "FAIL",
                    "total": leaf_spine_count,
                    "health_problems": leaf_spine_health_problem_count,
                    "cpu_problems": cpu_problem_count,
                    "mem_problems": mem_problem_count
                },
                "fabric": {
                    "status": "PASS" if fabric_health_ok else "FAIL",
                    "score": fabric_health
                },
                "faults": {
                    "critical": critical_faults,
                    "major": major_faults
                },
                "fcs_errors": {
                    "status": "PASS" if fcs_error_count == 0 else "FAIL",
                    "count": fcs_error_count,
                },
                "crc_errors": {
                    "status": "PASS" if crc_error_count == 0 else "FAIL",
                    "count": crc_error_count,
                },
                "drop_errors": {
                    "status": "PASS" if drop_error_count == 0 else "FAIL",
                    "count": drop_error_count,
                },
                "output_errors": {
                    "status": "PASS" if output_error_count == 0 else "FAIL",
                    "count": output_error_count,
                },
                "thresholds": {
                    "health": self.health_threshold,
                    "cpu_mem": self.cpu_mem_threshold,
                    "interface": self.interface_threshold
                }
            }

        def print_summary(self, summary_data: Dict):
            """Print summary panel"""
            summary_text = Text()

            # Overall status
            overall_color = "green" if summary_data["overall_status"] == "PASS" else "red"
            summary_text.append("OVERALL STATUS: ", style="bold")
            summary_text.append(f"{summary_data['overall_status']}\n", style=f"bold {overall_color}")
            summary_text.append("\n")

            # APIC Status
            apic_color = "green" if summary_data["apic"]["status"] == "PASS" else "red"
            summary_text.append("APIC Controllers: ", style="bold")
            summary_text.append(f"{summary_data['apic']['status']} ", style=apic_color)
            summary_text.append(f"({summary_data['apic']['problems']} of {summary_data['apic']['total']} with issues)\n")

            # Leaf/Spine Status
            leaf_spine_color = "green" if summary_data["leaf_spine"]["status"] == "PASS" else "red"
            summary_text.append("Leaf/Spine Nodes: ", style="bold")
            summary_text.append(f"{summary_data['leaf_spine']['status']} ", style=leaf_spine_color)
            summary_text.append(f"({summary_data['leaf_spine']['health_problems']} health, ")
            summary_text.append(f"{summary_data['leaf_spine']['cpu_problems']} CPU, ")
            summary_text.append(f"{summary_data['leaf_spine']['mem_problems']} memory issues)\n")

            # Fabric Status
            fabric_color = "green" if summary_data["fabric"]["status"] == "PASS" else "red"
            summary_text.append("Fabric Health: ", style="bold")
            summary_text.append(f"{summary_data['fabric']['status']} ", style=fabric_color)
            summary_text.append(f"(Score: {summary_data['fabric']['score']}%)\n")

            # Faults
            faults_total = summary_data["faults"]["critical"] + summary_data["faults"]["major"]
            faults_color = "green" if faults_total == 0 else "red"
            summary_text.append("Critical/Major Faults: ", style="bold")
            summary_text.append(f"{faults_total} ", style=faults_color)
            summary_text.append(f"({summary_data['faults']['critical']} critical, {summary_data['faults']['major']} major)\n")

            # Error summaries
            for error_type in ["fcs_errors", "crc_errors", "drop_errors", "output_errors"]:
                error_data = summary_data[error_type]
                error_color = "green" if error_data["status"] == "PASS" else "red"
                display_name = error_type.replace("_", " ").title()
                summary_text.append(f"{display_name}: ", style="bold")
                summary_text.append(f"{error_data['status']} ", style=error_color)
                summary_text.append(f"({error_data['count']} interfaces)\n")

            # Thresholds
            summary_text.append("\nThresholds: ", style="bold")
            summary_text.append(f"Health: {summary_data['thresholds']['health']}%, ")
            summary_text.append(f"CPU/Memory: {summary_data['thresholds']['cpu_mem']}%, ")
            summary_text.append(f"Interface: {summary_data['thresholds']['interface']} errors\n")

            self.console.print(Panel(summary_text, title="SUMMARY", style="bold"))
            self.console.print()

            # Final status panel
            status_msg = "✓ ALL CHECKS PASSED" if summary_data["overall_status"] == "PASS" else "✗ ISSUES DETECTED"
            status_style = "green" if summary_data["overall_status"] == "PASS" else "red"
            self.console.print(Panel(status_msg, style=status_style, expand=False))

    # -------------------- Data Savers -------------------- #

    class DataSaver:
        """Handles saving data to various formats"""
        
        def __init__(self, console: Console):
            self.console = console

        @staticmethod
        def ensure_dir(directory: str) -> bool:
            """Ensure directory exists, create if it doesn't
            
            Args:
                directory: Subdirectory name to create under aci/healthcheck/
                
            Returns:
                bool: True if directory exists or was created successfully, False otherwise
            """
            try:
                path = os.path.join("aci", "healthcheck", directory)
                os.makedirs(path, exist_ok=True)
                return os.path.exists(path) and os.path.isdir(path)
            except OSError as e:
                print(f"Error creating directory {directory}: {e}")
                return False
            except Exception as e:
                print(f"Unexpected error creating directory {directory}: {e}")
                return False

        def save_report_xlsx(self, data_dict: Dict[str, List[Dict]], output_dir: str) -> bool:
            """Save report as a single XLSX file with multiple sheets"""
            if not self.ensure_dir(output_dir):
                self.console.print(f"[red]Error creating directory {output_dir}[/red]")
                return False
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join("aci", "healthcheck", output_dir, f"aci_report_{timestamp}.xlsx")
            
            try:
                import pandas as pd
                
                sheet_configs = {
                    "apic_controllers": {
                        "data": data_dict.get("apic_nodes", []),
                        "columns": ["Hostname", "Serial", "IP", "Mode", "Status", "Health"],
                        "key_map": {
                            "Hostname": "name",
                            "Serial": "serial", 
                            "IP": "ip",
                            "Mode": "mode",
                            "Status": "status", 
                            "Health": "health_str"
                        }
                    },
                    "leaf_spine_nodes": {
                        "data": data_dict.get("leaf_spine_nodes", []),
                        "columns": ["Hostname", "Role", "Serial", "IP", "Version", "Uptime", "Health", "CPU", "Memory"],
                        "key_map": {
                            "Hostname": "name",
                            "Role": "role",
                            "Serial": "serial",
                            "IP": "ip", 
                            "Version": "version",
                            "Uptime": "uptime",
                            "Health": "health",
                            "CPU": "cpu", 
                            "Memory": "memory"
                        }
                    },
                    "faults": {
                        "data": data_dict.get("faults", []),
                        "columns": ["Severity", "Code", "Description", "Last Change", "DN"],
                        "key_map": {
                            "Severity": "severity",
                            "Code": "code",
                            "Description": "description", 
                            "Last Change": "last_change",
                            "DN": "dn"
                        }
                    },
                    "fcs_errors": {
                        "data": data_dict.get("fcs_errors", []),
                        "columns": ["Node", "Interface", "FCS Errors", "DN"],
                        "key_map": {
                            "Node": "node",
                            "Interface": "interface",
                            "FCS Errors": "fcs_errors",
                            "DN": "dn"
                        }
                    },
                    "crc_errors": {
                        "data": data_dict.get("crc_errors", []),
                        "columns": ["Node", "Interface", "CRC Errors", "DN"],
                        "key_map": {
                            "Node": "node",
                            "Interface": "interface", 
                            "CRC Errors": "crc_errors",
                            "DN": "dn"
                        }
                    },
                    "drop_errors": {
                        "data": data_dict.get("drop_errors", []),
                        "columns": ["Node", "Interface", "Drop Errors", "DN"],
                        "key_map": {
                            "Node": "node",
                            "Interface": "interface",
                            "Drop Errors": "drop_errors", 
                            "DN": "dn"
                        }
                    },
                    "output_errors": {
                        "data": data_dict.get("output_errors", []),
                        "columns": ["Node", "Interface", "Output Errors", "DN"],
                        "key_map": {
                            "Node": "node",
                            "Interface": "interface",
                            "Output Errors": "output_errors",
                            "DN": "dn"
                        }
                    }
                }

                with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                    for sheet_name, config in sheet_configs.items():
                        if config["data"]:
                            # Convert data to DataFrame
                            rows = []
                            for item in config["data"]:
                                row = {col: str(item.get(config["key_map"][col], "")) for col in config["columns"]}
                                rows.append(row)
                            
                            df = pd.DataFrame(rows, columns=config["columns"])
                            df.to_excel(writer, sheet_name=sheet_name, index=False)
                            
                            self.console.print(f"[green]✓ {sheet_name.replace('_', ' ').title()} sheet created[/green]")
                        else:
                            self.console.print(f"[yellow]⚠ No data for {sheet_name} sheet[/yellow]")

                self.console.print(f"[green]✓ All reports saved to {filename}[/green]")
                return True
                
            except ImportError:
                self.console.print("[red]Error: pandas and openpyxl are required for XLSX export. Install with: pip install pandas openpyxl[/red]")
                return False
            except Exception as e:
                self.console.print(f"[red]Error saving XLSX file: {str(e)}[/red]")
                return False

    # -------------------- Main Execution -------------------- #

    def run_health_check(self):
        """Main function to execute ACI health check"""
        # Get credentials
        self.apic_ip, username, password = self.get_credentials()

        # Login to APIC
        self.cookies = self.apic_login(self.apic_ip, username, password)
        if not self.cookies:
            sys.exit(1)

        # Initialize components
        api_client = self.APIClient(self.apic_ip, self.cookies, self.console)
        data_processor = self.DataProcessor()
        report_generator = self.ReportGenerator(
            self.console, 
            self.DEFAULT_HEALTH_THRESHOLD,
            self.DEFAULT_CPU_MEM_THRESHOLD, 
            self.DEFAULT_INTERFACE_ERROR_THRESHOLD
        )
        data_saver = self.DataSaver(self.console)

        # Fetch data with progress indication
        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
        ) as progress:
            progress.add_task(description="Collecting APIC health data...", total=None)
            apic_raw = api_client.fetch_apic_health()

            progress.add_task(description="Collecting node information...", total=None)
            top_raw = api_client.fetch_top_system()

            progress.add_task(description="Checking for faults...", total=None)
            faults_raw = api_client.fetch_faults()

            progress.add_task(description="Collecting CPU/Memory data...", total=None)
            cpu_raw, mem_raw = api_client.fetch_cpu_mem()

            progress.add_task(description="Checking fabric health...", total=None)
            fabric_raw = api_client.fetch_fabric_health()

            progress.add_task(description="Checking FCS errors...", total=None)
            fcs_raw = api_client.fetch_fcs_errors()

            progress.add_task(description="Checking CRC errors...", total=None)
            crc_raw = api_client.fetch_crc_errors()

            progress.add_task(description="Collecting drop errors...", total=None)
            drop_raw = api_client.fetch_drop_errors()

            progress.add_task(description="Collecting output errors...", total=None)    
            output_raw = api_client.fetch_output_errors()

        # Process data
        apic_nodes = data_processor.process_apic_data(apic_raw) if apic_raw else []
        leaf_spine_nodes = data_processor.process_leaf_spine(
            top_raw,
            cpu_raw if cpu_raw is not None else {},
            mem_raw if mem_raw is not None else {}
        ) if top_raw else []
        faults = data_processor.process_faults(faults_raw, 20) if faults_raw else []
        fabric_health = data_processor.process_fabric_health(fabric_raw) if fabric_raw else 0
        fcs_errors = data_processor.process_fcs_errors(fcs_raw, self.DEFAULT_INTERFACE_ERROR_THRESHOLD) if fcs_raw else []
        crc_errors = data_processor.process_crc_errors(crc_raw, self.DEFAULT_INTERFACE_ERROR_THRESHOLD) if crc_raw else []
        drop_errors = data_processor.process_drop_errors({"imdata": drop_raw}, self.DEFAULT_INTERFACE_ERROR_THRESHOLD) if drop_raw else []
        output_errors = data_processor.process_output_errors({"imdata": output_raw}, self.DEFAULT_INTERFACE_ERROR_THRESHOLD) if output_raw else []

        # Generate report
        report_generator.print_report(apic_nodes, leaf_spine_nodes, faults, fabric_health, 
                                    fcs_errors, crc_errors, drop_errors, output_errors)

        # Save data to files
        data_dict = {
            "apic_nodes": apic_nodes,
            "leaf_spine_nodes": leaf_spine_nodes, 
            "faults": faults,
            "fcs_errors": fcs_errors,
            "crc_errors": crc_errors,
            "drop_errors": drop_errors,
            "output_errors": output_errors
        }
                
        # Create reports directory
        reports_dir = "aci_reports"
                
        # Save to single XLSX file with multiple sheets
        success = data_saver.save_report_xlsx(data_dict, reports_dir)
        
def main_healthcheck_aci():
    """Main entry point"""
    checker = ACIHealthChecker()
    checker.run_health_check()


if __name__ == "__main__":
    main_healthcheck_aci()