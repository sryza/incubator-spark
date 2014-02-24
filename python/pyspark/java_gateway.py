#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from glob import glob
import os
import sys
import signal
import platform
from subprocess import Popen, PIPE
from threading import Thread
from py4j.java_gateway import java_import, JavaGateway, GatewayClient


def launch_gateway():
    SPARK_HOME = os.environ["SPARK_HOME"]

    # Add the pyspark zip to the YARN distributed files in case we're running
    # on YARN
    if "PYSPARK_ZIP" in os.environ:
        set_env_vars_for_yarn(os.environ["PYSPARK_ZIP"])

    # Launch the Py4j gateway using Spark's run command so that we pick up the
    # proper classpath and SPARK_MEM settings from spark-env.sh
    on_windows = platform.system() == "Windows"
    script = "./bin/spark-class.cmd" if on_windows else "./bin/spark-class"
    command = [os.path.join(SPARK_HOME, script), "py4j.GatewayServer",
               "--die-on-broken-pipe", "0"]
    if not on_windows:
        # Don't send ctrl-c / SIGINT to the Java gateway:
        def preexec_func():
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        proc = Popen(command, stdout=PIPE, stdin=PIPE, preexec_fn=preexec_func)
    else:
        # preexec_fn not supported on Windows
        proc = Popen(command, stdout=PIPE, stdin=PIPE)
    # Determine which ephemeral port the server started on:
    port = int(proc.stdout.readline())
    # Create a thread to echo output from the GatewayServer, which is required
    # for Java log output to show up:
    class EchoOutputThread(Thread):
        def __init__(self, stream):
            Thread.__init__(self)
            self.daemon = True
            self.stream = stream

        def run(self):
            while True:
                line = self.stream.readline()
                sys.stderr.write(line)
    EchoOutputThread(proc.stdout).start()
    # Connect to the gateway
    gateway = JavaGateway(GatewayClient(port=port), auto_convert=False)
    # Import the classes used by PySpark
    java_import(gateway.jvm, "org.apache.spark.SparkConf")
    java_import(gateway.jvm, "org.apache.spark.api.java.*")
    java_import(gateway.jvm, "org.apache.spark.api.python.*")
    java_import(gateway.jvm, "org.apache.spark.mllib.api.python.*")
    java_import(gateway.jvm, "scala.Tuple2")
    return gateway

def set_env_vars_for_yarn(pyspark_zip):
    if "SPARK_YARN_DIST_FILES" in os.environ:
        os.environ["SPARK_YARN_DIST_FILES"] += ("," + pyspark_zip)
    else:
        os.environ["SPARK_YARN_DIST_FILES"] = pyspark_zip
    
    # Add the pyspark zip to the python path
    env_map = parse_env(os.environ.get("SPARK_YARN_USER_ENV", ""))
    if "PYTHONPATH" in env_map:
        env_map["PYTHONPATH"] += (":" + os.path.basename(pyspark_zip))
    else:
        env_map["PYTHONPATH"] = os.path.basename(pyspark_zip)

    os.environ["SPARK_YARN_USER_ENV"] = ",".join(map(lambda v: v[0] + "=" + v[1],
        env_map.items()))

def parse_env(env_str):
    # Turns a comma-separated of env settings into a dict that maps env vars to
    # their values.
    env = {}
    for var_str in env_str.split(","):
        parts = var_str.split("=")
        if len(parts) == 2:
            env[parts[0]] = parts[1]
    
    return env
