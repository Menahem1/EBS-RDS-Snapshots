Snapshot Schedule is a product which makes it possible to schedule Snapshot on EC2 and RDS

it uses AWS Service : Lambda, DynamoDB and API of RDS and EC2

The lambda is scheduled every 5mn for checking the presence of tag that which will allow him to know if he has to backup

For EC2 you need to put the Tag Name "scheduler:ebs-snapshot" the Tag Value is custom

Custom value : <snapshot time>; <retention days>; <time zone>; <active day(s)>
Example "1030;15; us/pacific;mon,tue,fri"

By default the snapshot time is at 0330 AM, retention days : 30, time zone: Europe/Paris, active days : all

- Snapshot time : when the snapshot will occur (at which time)

- Retention Days : the number of days the snapshot will be kept

- Time Zone : On what time zone the snapshot will occur

- Active days : What day of the week the snapshot will happen 

For RDS the tag Name is "scheduler:rds-snapshot" and same syntax that for EC2 for Tag Value
The snapshot can be done as well on clusters RDS (Aurora) as instances

Resume:
Tag Name Example : Key : scheduler:rds-snapshot Value: "1030;15; us/pacific;mon,tue,fri"
