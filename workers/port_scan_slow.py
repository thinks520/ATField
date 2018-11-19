from app import celery
from datetime import datetime
from subprocess import call
from libnmap.parser import NmapParser
import os
from celery.signals import before_task_publish, task_postrun
from app.models.assets import Host
from app.models.tasks import Task
from workers.result import save


@before_task_publish.connect(sender="workers.port_scan_slow.worker")
def before(sender=None, headers=None, body=None, properties=None, **kw):
    targets = ' '.join([host.name for host in Host.query.all()])
    task = Task.insert_task_and_return("port scan slow", "timed", "", "周期nmap慢扫", targets)
    body[1]["targets"] = targets
    headers["id"] = task.id


@task_postrun.connect()
def after(sender=None, task_id=None, retval=None, **kw):
    if sender.name == "workers.port_scan_slow.worker":
        save.apply_async(args=(retval, task_id))


@celery.task(bind=True)
def worker(self, targets, options):
    result = {
        "start_time": datetime.utcnow(),
        "end_time": datetime.utcnow(),
        "result": {
            "total": len(targets.split()),
            "failed": 0,
            "details": []
        }
    }
    count = 0
    self.update_state(state="PROGRESS", meta={'progress': count/len(targets.split())})

    for ip in targets.split():
        temp_file = "nmap.log"
        scan_cmd = "nmap {} -oX {} {}".format(options, temp_file, ip)
        call(scan_cmd, shell=True)

        item = {}

        try:
            parser_result = NmapParser.parse_fromfile(temp_file)
            item["start_time"] = parser_result.started
            item["end_time"] = parser_result.endtime
            item["elasped"] = parser_result.elapsed
            item["commandline"] = parser_result.commandline
            item["ip"] = ip
            item["error"] = ""
            item["services"] = []

            for host in parser_result.hosts:
                for service in host.services:
                    service_item = {
                        "port": service.port,
                        "tunnel": service.tunnel,
                        "protocol": service.protocol,
                        "state": service.state,
                        "service": service.service,
                        "banner": service.banner,
                    }
                    item["services"].append(service_item)
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception as e:
            item["error"] = e.__repr__()
            result["result"]["failed"] += 1

        result["result"]["details"].append(item)
        count += 1
        self.update_state(state="PROGRESS", meta={'progress': count/len(targets.split())})

    result["end_time"] = datetime.utcnow()
    return result