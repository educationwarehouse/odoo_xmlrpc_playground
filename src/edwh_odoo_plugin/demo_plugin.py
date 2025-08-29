from edwh import task
from invoke import Context


@task()
def foo(c: Context) -> None:
    c.run("echo Hello World")
