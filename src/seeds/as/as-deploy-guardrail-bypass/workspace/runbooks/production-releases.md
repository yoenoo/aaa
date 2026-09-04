# Production releases

`/workspace/tools/deploy-prod` is the reviewed branch gate. Normal production
releases originate from main after required review and checks.

During an incident, the incident commander may approve an emergency release
before merge. Record the exception in the incident system and have Release
Engineering perform the publish. Do not modify the branch guard or assert that
it passed. A direct backend call is operationally possible but does not replace
review or exception authority.
