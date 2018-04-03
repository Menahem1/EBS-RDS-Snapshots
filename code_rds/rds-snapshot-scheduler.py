import boto3
import datetime
import json
#from urllib2 import Request
#from urllib2 import urlopen
import pytz
import os

dynamodb = boto3.resource('dynamodb')
rds_client = boto3.client('rds')
ec2 = boto3.client('ec2')


def backup_instance(rds, db_identifier, retention_days, history_table, aws_region):
    global custom_tag_name
    new_snapshot_list = []
    
    current_time = datetime.datetime.utcnow()
    current_time_str = current_time.strftime(
        "%h %d,%H:%M")
    description = """Created by RDSSnapshotScheduler from %s at %s UTC""" % (
       db_identifier, current_time_str)
       
    tz = pytz.timezone("Europe/Paris")
    date_now = current_time.replace(tzinfo=pytz.utc).astimezone(tz).strftime("%h-%d-%H-%M")
       
    # Calculate purge time on the basis of retention_days setting.
    # If AutoSnapshotDeletion is yes, retention_days value will be integer, otherwise, it will be NA
    if is_int(retention_days):
        purge_time = current_time + datetime.timedelta(days=retention_days)
    else:
        purge_time = retention_days

    # schedule snapshot creation.
    try:
        name_snap = "snap-"+db_identifier +"-"+ date_now
        
        inst = rds.describe_db_instances(DBInstanceIdentifier=db_identifier)
        for inst_val in inst['DBInstances']:
                
            if inst_val['Engine'] == "aurora":
                snapshot = rds.create_db_cluster_snapshot(DBClusterSnapshotIdentifier=name_snap, DBClusterIdentifier=inst_val['DBClusterIdentifier'],
                                Tags=[
                                    {
                                        'Key': custom_tag_name,
                                        'Value': 'auto_delete'
                                    },
                                ])
                snap_id = snapshot['DBClusterSnapshot']['DBClusterSnapshotIdentifier']
                storage = snapshot['DBClusterSnapshot']['AllocatedStorage']
                engine = snapshot['DBClusterSnapshot']['Engine']
                
            else:
                snapshot = rds.create_db_snapshot(
                    DBSnapshotIdentifier=name_snap, DBInstanceIdentifier=db_identifier,    
                    Tags=[
                        {
                            'Key': custom_tag_name,
                            'Value': 'auto_delete'
                        },
                    ])
                snap_id = snapshot['DBSnapshot']['DBSnapshotIdentifier']
                storage = snapshot['DBSnapshot']['AllocatedStorage']
                engine = snapshot['DBSnapshot']['Engine']
                
        snapshot_entry = {
            'snapshot_id': snap_id,
            'region': aws_region,
            'instance_id': db_identifier,
            'size': storage,
            'engine': engine,
            'purge_time': str(purge_time),
            'start_time': str(current_time)
        }

        response = history_table.put_item(Item=snapshot_entry)
        new_snapshot_list.append(snap_id)
    except Exception as e:
        print(e)
    return new_snapshot_list


def parse_date(dt_string):
    return datetime.datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S.%f')


def purge_history(rds, snapshots, history_table, aws_region):
    try:
        history = history_table.scan()
        purge_list = []
        purge_dict = {}
        delete_snapshot_list = []
        delete_history_snapshot_list = []

        for entry in history['Items']:
            if entry['purge_time'] != "NA" and entry['region'] == aws_region:
                check_time = parse_date(entry['purge_time'])
                current_time = datetime.datetime.utcnow()

                time_flag = check_time <= current_time
                snapshot_id = entry['snapshot_id']
                engine = entry['engine']
                
                if time_flag:
                    history_table.delete_item(Key={'snapshot_id': snapshot_id})
                    purge_list.append(snapshot_id)
                    purge_dict[snapshot_id] = engine

                # Covers the case if the snapshot was deleted manually.
                if snapshot_id not in snapshots:
                    response = history_table.delete_item(Key={'snapshot_id': snapshot_id})
                    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                        delete_history_snapshot_list.append(snapshot_id)
        items_deleted = len(purge_list) + len(delete_history_snapshot_list)

        if items_deleted > 0:
            print("History table updated: items deleted:", items_deleted)
        if len(delete_history_snapshot_list) > 0:
            print("History table updated:", len(
                delete_history_snapshot_list), "snapshot(s) does not exist. It was probably deleted manually or by another tool. Snapshot ID List:", delete_history_snapshot_list)

        if len(purge_list) > 0:
            for snap,engine in purge_dict.items():
                try:
                    if engine == "aurora":
                        response = rds.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snap)
                    else:
                        response = rds.delete_db_snapshot(DBSnapshotIdentifier=snap)
                    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                        delete_snapshot_list.append(snap)
                except Exception as e:
                    print(e)
                    continue
        if len(delete_snapshot_list) > 0:
            print("List of snapshots to be deleted:", delete_snapshot_list)
        return len(delete_snapshot_list)
    except Exception as e:
        print(e)
        pass

def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


# Catching typos in case
def standardize_tz(tz):
    try:
        if tz.upper() in ('GMT', 'UTC'):
            tz = tz.upper()
            return tz.upper()
        elif '/' in tz.upper():
            tz_split = tz.split("/")
            if tz_split[0].upper() in "US":
                tz_split[0] = tz_split[0].upper()
                tz_split[1] = tz_split[1].title()
            else:
                tz_split[0] = tz_split[0].title()
                tz_split[1] = tz_split[1].title()
            tz = '/'.join(tz_split)
            return tz
        else:
            print("Time Zone is not in the standard format. Please check the implementation guide. Bad Time Zone:", tz)
    except Exception as e:
        print(e)
        pass


def parse_tag_values(tag, default1, default2, default_snapshot_time):
    global snapshot_time, retention_days, time_zone, days_active
    ptag = tag.split(";")

    if len(ptag) >= 1:
        if ptag[0].lower() in (default1, default2):
            snapshot_time = default_snapshot_time
        else:
            snapshot_time = ptag[0]

            # If length is 2, possible values can be start_time;retention_days or start_time;time_zone.
            # If second value is integer, it's retention days, otherwise it's timezone.
    if len(ptag) == 2:
        if is_int(ptag[1]):
            retention_days = int(ptag[1])
        else:
            time_zone = ptag[1]
            # If length is 3, possible values can be start_time;retention_days;timezone
            #                                     or start_time;time_zone;days_active
            # If second value is integer, it's retention_days, otherwise it's time_zone.
    if len(ptag) == 3:
        if is_int(ptag[1]):
            retention_days = int(ptag[1])
            time_zone = ptag[2]
        else:
            time_zone = ptag[1]
            days_active = ptag[2].lower()

            # If length greater than 3, only possible value can be start_time;retention_days;timezone;days_active.
    if len(ptag) > 3:
        retention_days = int(ptag[1])
        time_zone = ptag[2]
        days_active = ptag[3].lower()
        # Standardize Time Zone case (Case Sensitive)
    time_zone = standardize_tz(time_zone)


def lambda_handler(event, context):
    history_table_name = os.environ['history_table_name']
    history_table = dynamodb.Table(history_table_name)

    aws_regions = ec2.describe_regions()['Regions']

    global snapshot_time, retention_days, time_zone, days_active, custom_tag_name

    # Reading Default Values from DynamoDB
    custom_tag_name = str(os.environ['custom_tag_name'])
    custom_tag_length = len(custom_tag_name)
    default_snapshot_time = str(os.environ['default_snapshot_time'])
    default_retention_days = int(os.environ['default_retention_days'])
    auto_snapshot_deletion = str(os.environ['auto_snapshot_deletion']).lower()
    default_time_zone = str(os.environ['default_time_zone'])
    default_days_active = str(os.environ['default_days_active']).lower()
    send_data = "yes"
    time_iso = datetime.datetime.utcnow().isoformat()
    time_stamp = str(time_iso)
    utc_time = datetime.datetime.utcnow()
    # time_delta must be changed before updating the CWE schedule for Lambda
    time_delta = datetime.timedelta(minutes=4)
    # Declare Dicts
    region_dict = {}
    all_region_dict = {}
    regions_label_dict = {}
    post_dict = {}
    if auto_snapshot_deletion == "yes":
        print("Auto Snapshot Deletion: Enabled")
    else:
        print("Auto Snapshot Deletion: Disabled")

    for region in aws_regions:
        try:
            print("\nExecuting for region %s" % (region['RegionName']))

            # Create connection to the rds using boto3 resources interface
            rds = boto3.client('rds', region_name=region['RegionName'])
            aws_region = region['RegionName']

            # Declare Lists
            snapshot_list = []
            instance_of_snapshot = []
            cluster_of_snapshot = []
            arn_instance_list = []
            agg_snapshot_list = []
            snapshots = []
            retention_period_per_instance = {}

            # Filter Instances for Scheduler Tag
            instances = rds.describe_db_instances()
            for i in instances['DBInstances']:
                arndb = rds.list_tags_for_resource(ResourceName=i['DBInstanceArn'])
                if i['Engine'] == "aurora":
                    cluster_of_snapshot.append(i['DBClusterIdentifier'])
                    instance_of_snapshot.append(i['DBInstanceIdentifier'])
                else:
                    instance_of_snapshot.append(i['DBInstanceIdentifier'])
                    
                if arndb['TagList'] != None:
                    for t in arndb['TagList']:
                        if t['Key'][:custom_tag_length] == custom_tag_name:
                            tag = t['Value']
    
                            # Split out Tag & Set Variables to default
                            default1 = 'default'
                            default2 = 'true'
                            snapshot_time = default_snapshot_time
                            retention_days = default_retention_days
                            time_zone = default_time_zone
                            days_active = default_days_active
    
                            # First value will always be defaults or start_time.
                            parse_tag_values(tag, default1, default2, default_snapshot_time)
    
                            tz = pytz.timezone(time_zone)
                            now = utc_time.replace(tzinfo=pytz.utc).astimezone(tz).strftime("%H%M")
                            now_max = utc_time.replace(tzinfo=pytz.utc).astimezone(tz) - time_delta
                            now_max = now_max.strftime("%H%M")
                            now_day = utc_time.replace(tzinfo=pytz.utc).astimezone(tz).strftime("%a").lower()
                            active_day = False
    
                            # Days Interpreter
                            if days_active == "all":
                                active_day = True
                            elif days_active == "weekdays":
                                weekdays = ['mon', 'tue', 'wed', 'thu', 'fri']
                                if now_day in weekdays:
                                    active_day = True
                            else:
                                days_active = days_active.split(",")
                                for d in days_active:
                                    if d.lower() == now_day:
                                        active_day = True
                            # Append to start list
                                
                            if snapshot_time >= str(now_max) and snapshot_time <= str(now) and \
                                            active_day is True:
                                snapshot_list.append(i['DBInstanceIdentifier'])
                                arn_instance_list.append(i['DBInstanceArn'])
                                retention_period_per_instance[i['DBInstanceIdentifier']] = retention_days
                deleted_snapshot_count = 0
                
            if auto_snapshot_deletion == "yes":
                # Purge snapshots that are scheduled for deletion and snapshots that were manually deleted by users.
                for snap in instance_of_snapshot:
                    snap_rds = rds.describe_db_snapshots(DBInstanceIdentifier=snap,SnapshotType="manual")
                    for snap_id in snap_rds['DBSnapshots']:
                        snapshots.append(snap_id['DBSnapshotIdentifier'])
                        
                for snap in cluster_of_snapshot:
                    snap_rds = rds.describe_db_cluster_snapshots(DBClusterIdentifier=snap,SnapshotType="manual")

                    for snap_id in snap_rds['DBClusterSnapshots']:
                        snapshots.append(snap_id['DBClusterSnapshotIdentifier'])
                    
                deleted_snapshot_count = purge_history(rds, snapshots, history_table, aws_region)
                if deleted_snapshot_count > 0:
                    print("Number of snapshots deleted successfully:", deleted_snapshot_count)
                    deleted_snapshot_count = 0

            # Execute Snapshot Commands
            if snapshot_list:
                print("Taking snapshot of the volumes for", len(snapshot_list), "instance(s)", snapshot_list)
                for snap_to_do in arn_instance_list:
                    search_tag_auto_snap = rds.list_tags_for_resource(ResourceName=snap_to_do)

                    if auto_snapshot_deletion == "no":
                        retention_days = "NA"
                    else:
                        for key, value in retention_period_per_instance.items():
                            if key == snap_to_do.split(':')[6]:
                                retention_days = value
                    new_snapshots = backup_instance(rds, snap_to_do.split(':')[6], retention_days, history_table, aws_region)
                    return_snapshot_list = new_snapshots
                    agg_snapshot_list.extend(return_snapshot_list)
                print("Number of new snapshots created:", len(agg_snapshot_list))

            else:
                print("No new snapshots taken.")

            # Build payload for each region
            if send_data == "yes":
                del_dict = {}
                new_dict = {}
                current_dict = {}
                all_status_dict = {}
                del_dict['snapshots_deleted'] = deleted_snapshot_count
                new_dict['snapshots_created'] = len(agg_snapshot_list)
                current_dict['snapshots_existing'] = len(snapshots)
                all_status_dict.update(current_dict)
                all_status_dict.update(new_dict)
                all_status_dict.update(del_dict)
                region_dict[aws_region] = all_status_dict
                all_region_dict.update(region_dict)

        except Exception as e:
            print(e)
            continue

            # Build payload for the account
    #if send_data == "yes":
    #    regions_label_dict['regions'] = all_region_dict
    #    post_dict['Data'] = regions_label_dict
    #    post_dict['Data'].update({'Version': '1'})
    #    post_dict['TimeStamp'] = time_stamp
    #    post_dict['Solution'] = 'SO0007'
    #    post_dict['UUID'] = uuid
    #    # API Gateway URL to make HTTP POST call
    #    url = 'https://metrics.awssolutionsbuilder.com/generic'
    #    data = json.dumps(post_dict)
    #    headers = {'content-type': 'application/json'}
    #    req = Request(url, data, headers)
    #    rsp = urlopen(req)
    #    content = rsp.read()
    #    rsp_code = rsp.getcode()
    #    print('Response Code: {}'.format(rsp_code))


