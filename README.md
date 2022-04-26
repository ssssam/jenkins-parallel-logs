# Jenkins parallel log fetcher

This commandline tool fetches build logs from Jenkins. It fetches a separate
log for each build step, which is necessary when 'parallel' or 'matrix' blocks are used.

Example usage:

     env JENKINS_URL='https://jenkins.example.com/'  python3 jpl.py 'my-test-job' 1 jenkins/ --only-icon-color red 

Based on StackOverflow answer:

  * https://stackoverflow.com/a/38878120

Relevant upstream Jenkins issues:

  * https://issues.jenkins.io/browse/JENKINS-55258 ("Support scanning of console log with parallel steps")

License: MIT
