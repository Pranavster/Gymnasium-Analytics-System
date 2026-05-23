-- Retention / Churn
-- 		churn_rate: users who cease to be active after one month
create or replace view gym_analytics.churn_rate_30d_view as
with member_last_activity as (
	select 
		member_id,
		max(date) as last_activity_date
	from gym_analytics.fact_activity_daily
	group by member_id
),
churned_members as (
	select member_id
	from member_last_activity
	where last_activity_date < CURRENT_DATE - between '30 days'
),
totals as (
	select count(*) as total_members
	from gym_analytics.dim_members
)

select
	count(*)::numeric / total_members 
from churned_members, totals;

create or replace view gym_analytics.retention_rate_30d_view as
with cohort as (
	select member_id, signup::date as signup_date
	from gym_analytics.dim_members
),
retained as (
	select distinct co.member_id
	from cohort co
	join gym_analytics.fact_activity_daily ad
		on co.member_id = ad.member_id
	where ad.date >= co.signup_date + between '30 days'
),

counts as (
	select
		(select count(*) from cohort) as total_members,
		(select count(*) from retained) as retained_members	
)

select
	retained_members::numeric / total_members as retention_rate_30d, retained_members::numeric, total_members
from counts;

select * from retention_rate_30d_view;

-- 
with cohort as (
	select
		member_id,
		date_trunc('month', signup) as cohort_month
	from gym_analytics.dim_members
),

activity as (
	select distinct
		member_id,
		date_trunc('month', date) as activity_month
	from gym_analytics.fact_activity_daily
),

-- cohort retention

cohort_activity as (
	select
		co.cohort_month,
		ac.activity_month,
		count(distinct co.member_id) as active_members
	from cohort co
	join activity ac
		on co.member_id = ac.member_id
	group by co.cohort_month, ac.activity_month
)

select *
from cohort_activity
order by cohort_month, activity_month;

-- Engagement
-- 		avg bookings per member: average amount of bookings per members over a rolling 30 day window
with booking_activity as (
    select
        booking_time::date as activity_date,
        member_id
    from gym_analytics.fact_bookings
),

calendar as (
    select distinct activity_date
    from booking_activity
),
rolling_metrics as (
    select
        c.activity_date,

        count(*) as rolling_bookings,

        count(distinct b.member_id) as rolling_members

    from calendar c
    join booking_activity b
        on b.activity_date
        BETWEEN c.activity_date - between '29 days'
        and c.activity_date

    group by c.activity_date
)

select
    activity_date,

    rolling_bookings,
    rolling_members,

    ROUND(
        rolling_bookings::numeric
        / NULLIF(rolling_members, 0),
        2
    ) as avg_bookings_per_member_30d

from rolling_metrics
order by activity_date;
select * from gym_analytics.fact_class_sessions; -- status booking not completed

--			cancellation_rate Rate at which members cancelled previously booked meetings
select
    member_id,
    count(case when (is_cancelled = True) then 1 END)::float
    /
    nullif(count(*), 0) as cancellation_rate
from gym_analytics.fact_bookings
where booking_time >= CURRENT_DATE - between '30 days'
group by member_id
order by member_id;
--			no_show_rate: The rate of people who booked meetings but did not cancel and did not show up
select
    member_id,
    count(case when (is_no_show = True) then 1 END)::float
    /
    nullif(count(*), 0) as no_show_rate
from gym_analytics.fact_bookings
where booking_time >= CURRENT_DATE - between '30 days'
group by member_id
order by member_id;

-- 		diversity number of unique class types attended per member in rolling 30-day window
select fb.member_id, count(distinct cl.class_type) as class_types from gym_analytics.fact_bookings fb 
join gym_analytics.classes cl on fb.class_id = cl.class_id where fb.booking_time >= CURRENT_DATE - between '30 days'
group by fb.member_id order by fb.member_id;


-- Business Metrics
-- 		revenue per member: How much total revenue an individual member generates (over a rolling 30 day window? 
-- and if so which one? the last 30 day period? 1 month since signup?)

select pay.member_id, sum( pay.amount )
from gym_analytics.payments pay
group by pay.member_id
order by pay.member_id;

select pay.member_id, sum( pay.amount ) 
from gym_analytics.payments pay where payment_date >= CURRENT_DATE - between '30 days'
group by pay.member_id
order by pay.member_id;

-- 		revenue per class: How much total revenue a class generates over a rolling 30 day window?

select
    fb.class_id,
    count(*) as bookings
from gym_analytics.fact_bookings fb
where fb.is_attended = TRUE
group by fb.class_id;

-- 		trainer workload: utilization = booked training hours

select
    trainer_id,
    SUM(EXTRACT(EPOCH from (end_time - start_time)) / 3600) as booked_hours
from gym_analytics.fact_class_sessions
group by trainer_id;

-- inactive members: when a member had no activity in 30 days

create or replace view gym_analytics.inactive_members as
select
    dm.member_id
from gym_analytics.dim_members dm
left join gym_analytics.fact_activity_daily ad
    on dm.member_id = ad.member_id
    and ad.date >= CURRENT_DATE - between '30 days'
where ad.member_id IS NULL;