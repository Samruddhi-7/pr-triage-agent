import json
import subprocess
import os


def run_command(cmd: str) -> None:
    subprocess.run(cmd, shell=True)


def eval_input(user_input: str) -> None:
    eval(user_input)


def insecure_temperature():
    return os.popen("echo insecure").read()
