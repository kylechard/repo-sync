#!/usr/bin/env python

from __future__ import absolute_import
from multiprocessing import Lock

"""
Simple app to monitor a remote git repository and update the local
when changes have been made. This is primarily design to support
automatic deployment of websites based on git commits.

Usage: sync.py [options]

Options:
  -h, --help            show this help message and exit
  -i INTERVAL, --interval=INTERVAL
                        Interval to check git
  -b BRANCH, --branch=BRANCH
                        Which branch should be checked
  -v, --verbose         More output
  -V, --wicked-verbose  Wicked more output

"""

import logging
import optparse
import os
import sched
import signal
from subprocess import Popen, PIPE, check_call
import sys
import time

log = logging.getLogger()

scheduler = sched.scheduler(time.time, time.sleep)

class GitUpdater(object):
  """
  Thin wrapper around git and sched which checks to see if there have been changes to the
  remote repository that have not yet been updated in the local repository. This only
  suupport checking a single branch. If there have been changes, this will pull the new
  changes into the local repo.

  This allows you to specify the interval at which to check for changes and the branch to
  check.
  """

  def __init__(self, mutx, repos, interval, branch, callback):
    self.mutx = mutx
    self.interval = interval
    self.branch = branch
    self.callback = callback
    self.repos = repos
    for repo in self.repos:
      log.info("Monitoring remote repo for: {0}".format(repo))
    scheduler.enter(interval, 1, self.update_from_git, ())

  def update_from_git(self):
    self.mutx.acquire()
    current_path = os.getcwd()
    for repo in self.repos:
      os.chdir(repo)
      git_fetch = Popen(['git', 'fetch'], stdout=PIPE, stderr=PIPE)
      result = git_fetch.communicate()
      if git_fetch.returncode != 0:
        log.warn("Error fetching remote repo")
        log.warn("{0}\n{1}".format(result[1], result[0]))
      current_ref = Popen(['git', 'symbolic-ref', 'HEAD'], stdout=PIPE).communicate()[0].strip()
      if current_ref != 'refs/heads/{0}'.format(self.branch):
        log.info('Repository is currently on: {0}.  Switching to: refs/heads/{1}'.format(current_ref, self.branch))
        check_call(['git', 'checkout', self.branch])
      local_hash = Popen(['git', 'rev-parse', 'HEAD'], stdout=PIPE).communicate()[0].strip()
      p1 = Popen(['git', 'ls-remote', 'origin', self.branch], stdout=PIPE)
      p2 = Popen(['awk', '{print $1}'], stdin=p1.stdout, stdout=PIPE)
      p1.stdout.close()
      remote_hash = p2.communicate()[0].strip()
      log.debug('Repo: {0}. Local hash: {1}.  Remote hash: {2}'.format(repo, local_hash, remote_hash))
      if local_hash != remote_hash:
        log.info('Updating local repository: {0} to: {1}'.format(repo, remote_hash))
        check_call(['git', 'pull', 'origin', self.branch])
        if self.callback is not None:
          log.info('Calling callback for {0}'.format(repo))
          result = Popen([self.callback], stdout=PIPE, stderr=PIPE).communicate()
          log.debug("Callback result for: {0}.  {1}".format(repo, result))
      else:
        log.debug("No updates to retrieve for {0}".format(repo))
    os.chdir(current_path)
    scheduler.enter(self.interval, 1, self.update_from_git, ())
    self.mutx.release()

  def start(self):
    scheduler.run()

  def stop(self):
    if not scheduler.empty:
      for event in scheduler.queue:
        try:
          scheduler.cancel(event)
        except ValueError:
          log.debug('Job beat us to the shutdown punch: {0}'.format(event))
    self.mutx.release()

def kill_handler(signal, frame):
  log.info('Shutting Down')
  if not scheduler.empty:
    for event in scheduler.queue:
      try:
        scheduler.cancel(event)
      except ValueError:
        log.debug('Job beat us to the shutdown punch: {0}'.format(event))
  self.mutx.release()
  sys.exit(0)

if __name__ == "__main__":
  parser = optparse.OptionParser()
  parser.add_option('-i', '--interval', action="store", dest="interval", default=5, type="int", help="Interval to check git")
  parser.add_option('-b', '--branch', action="store", dest="branch", default="integration", help="Which branch should be checked")
  parser.add_option('-c', '--callback', action="store", dest="callback", default=None, help="Script to be called upon changes")
  parser.add_option('-v', '--verbose', action="store_true", dest="verbose", default=False, help="More output")
  parser.add_option('-V', '--wicked-verbose', action='store_true', dest="wicked_verbose", default=False, help="Wicked more output")
  options, remainder = parser.parse_args();
  log_level = logging.WARNING
  if options.verbose and options.wicked_verbose:
    print('Dude, do you want more output or wicked more output (Please use either -v or -V, not both)')
    sys.exit(1)
  if options.verbose:
    log_level = logging.INFO
  if options.wicked_verbose:
    log_level = logging.DEBUG
  logging.basicConfig(level=log_level, format="%(levelname)s - %(asctime)s (%(name)s:%(funcName)s):  %(msg)s")
  signal.signal(signal.SIGINT, kill_handler)
  updater = GitUpdater(None, options.interval, options.branch, options.callback)
  updater.start()
