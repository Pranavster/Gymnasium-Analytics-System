-- Membership & Retention

-- #1: What member behaviors within the first 30 days (e.g., bookings, attendance, cancellations) are most predictive of churn?

create or replace view gym_analytics.churn_implication as
	with churn_implication as (
		select
			fb.member_id,
			count(*) as total_bookings,
			count(*) filter (where fb.is_attended = true) as total_attendance,
			count(*) filter (where fb.is_cancelled = true) as total_cancellations,
			count(*) filter (where fb.is_cancelled = true and fb.cancellation_time <= fb.class_time - interval '24 hours') as early_cancellations,
			count(*) filter (where fb.is_cancelled = true
				  and fb.cancellation_time > fb.class_time - interval '24 hours'
			) as late_cancellations,
			count(*) filter (where fb.is_no_show = true)::float
			/
			nullif(count(*),0) as no_show_rate,
			(current_date - min(fb.booking_time)::date) as tenure_days,
			least(count(*)::float / 8.0, 1.0)
				as booking_frequency_score,
			count(*) filter (where fb.is_attended = true)::float
			/
			nullif(count(*)
				- count(*) filter (where fb.is_cancelled = true and fb.cancellation_time <= fb.class_time - interval '24 hours')
				- count(*) filter (where fb.is_cancelled = true and fb.cancellation_time > fb.class_time - interval '24 hours'),
				0) as attendance_consistency,
			count(*) filter (where fb.is_cancelled = true and fb.cancellation_time > fb.class_time - interval '24 hours')::float
			/
			nullif(count(*), 0)
				as late_cancellation_rate
		from gym_analytics.fact_bookings fb
		where fb.booking_time >= current_date - interval '30 days'
		group by fb.member_id
		order by fb.member_id
	)
select * from gym_analytics.churn_implication;

-- #2: Does participation in certain class types correlate with higher or lower member retention?

create or replace view gym_analytics.retained_after_30d_by_member as
	with cohort as (
		select member_id, signup::date as signup_date from gym_analytics.dim_members
	),
	retained as (
		select distinct co.member_id from cohort co join gym_analytics.fact_activity_daily ad on co.member_id = ad.member_id 
		where ad.date >= co.signup_date + interval '30 days' and ad.date < co.signup_date + interval '60 days'
	)
	select
		co.member_id,
		case
			when r.member_id is not NULL then 1
			else 0
		end as retained_after_30d
	from cohort co
	left join retained r on co.member_id = r.member_id;
	
create or replace view gym_analytics.class_type_retention_association as
	with member_classes as (
		select distinct fb.member_id, cl.class_type from gym_analytics.fact_bookings fb 
		join gym_analytics.classes cl on fb.class_id = cl.class_id join gym_analytics.dim_members dm on fb.member_id = dm.member_id
		where fb.booking_time >= dm.signup::date and fb.booking_time <  dm.signup::date + interval '7 days'
	),
	retention as (
		select *
		from gym_analytics.retained_after_30d_by_member
	)
	select
		mc.class_type, count(distinct mc.member_id) as members, avg(r.retained_after_30d::numeric) as retention_rate_30d
	from member_classes mc
	join retention r on mc.member_id = r.member_id
	group by mc.class_type
	order by retention_rate_30d desc;

select * from gym_analytics.class_type_retention_association;

-- #3: Is there a relationship between trainer pricing (or session cost) and member retention? 

create or replace view gym_analytics.vw_trainer_price_churn_features as
	with sessions_labeled as (
		select
			ts.member_id, ts.trainer_id, ts.rate_charged, ts.session_id,
			case
				when ts.rate_charged < 25 then 'low'
				when ts.rate_charged < 75 then 'medium'
				else 'high'
			END as price_tier
		from gym_analytics.trainer_sessions ts
	),
	member_price_exposure as (
		select
			member_id, count(*) as total_sessions, AVG(rate_charged) as avg_session_price,
			sum(case when price_tier = 'low' then 1 else 0 END)::float / count(*) as pct_low_price,
			sum(case when price_tier = 'medium' then 1 else 0 END)::float / count(*) as pct_medium_price,
			sum(case when price_tier = 'high' then 1 else 0 END)::float / count(*) as pct_high_price
		from sessions_labeled
		group by member_id
	),
	engagement as (
		select
			fb.member_id,
			count(*) as total_bookings, count(*) filter (where fb.is_attended = true) as attended,
			MIN(fb.booking_time) as first_booking, MAX(fb.booking_time) as last_booking
		from gym_analytics.fact_bookings fb
		group by fb.member_id
	),
	engagement_features as (
		select
			member_id, total_bookings, attended, attended::float / nullif(total_bookings, 0) as attendance_rate,
			CURRENT_DATE - first_booking::date as tenure_days
		from engagement
	),
	churn as (
		select
			member_id, churned
		from gym_analytics.dim_members
	)
	select
		ch.member_id, ch.churned,
		mpe.avg_session_price, mpe.pct_low_price, mpe.pct_medium_price, mpe.pct_high_price, mpe.total_sessions,
		ef.total_bookings, ef.attendance_rate, ef.tenure_days
	from churn ch
	LEFT join member_price_exposure mpe on ch.member_id = mpe.member_id
	LEFT join engagement_features ef on ch.member_id = ef.member_id;

select * from gym_analytics.vw_trainer_price_churn_features;

-- #4: Do members who predominantly attend high capacity classes display different churn rates compared to those in lower capacity classes?

create or replace view gym_analytics.vw_capacity_churn_rates as
	select
		case
			when dc.capacity >= 20 then 'High capacity (≥20)'
			else 'Low capacity (<20)'
		END as capacity_bucket,
		count(distinct fb.member_id) as total_members,
		count(distinct case when dm.churned = TRUE then fb.member_id END) as churned_members,
		round(100.0 * count(distinct case when dm.churned = TRUE then fb.member_id END) / nullif(count(distinct fb.member_id), 0), 1) as churn_rate_pct
	from gym_analytics.fact_bookings fb
	join gym_analytics.dim_classes dc on fb.class_id = dc.class_id
	join gym_analytics.dim_members dm on fb.member_id = dm.member_id
	group by
		case
			when dc.capacity >= 20 then 'High capacity (≥20)'
			else 'Low capacity (<20)'
		END,
		dc.capacity
	order by
		case
			when dc.capacity >= 20 then 1 else 0
		END;

select * from gym_analytics.vw_capacity_churn_rates;
-- Classes

-- #5: Which trainers consistently achieve higher class fill rates, and how do they compare to average?

create or replace view gym_analytics.vw_time_slot_utilization as
	with fcs_class_time as (
		select
			fcs.class_session_id, fcs.class_id, fcs.start_time, fcs.end_time, fcs.fill_rate,
			case
				when fcs.start_time::time >= '06:00:00' and fcs.start_time::time < '12:00:00' then 'morning'
				when fcs.start_time::time >= '12:00:00' and fcs.start_time::time < '16:30:00' then 'afternoon'
				when fcs.start_time::time >= '16:30:00' and fcs.start_time::time < '21:00:00' then 'evening'
				else 'off_hours'
			end as class_time_bucket
		from gym_analytics.fact_class_sessions fcs
	),

	attendance_analysis as (
		select
			fct.class_time_bucket,
			count(*) as total_bookings,
			count(
				case
					when fb.is_attended = true then 1
				end
			) as attended_bookings,
			round(
				count(
					case
						when fb.is_attended = true then 1
					end
				)::numeric
				/
				nullif(count(*), 0),
				4
			) as attendance_rate,
			round(avg(fct.fill_rate)::numeric, 2) as avg_fill_rate
		from gym_analytics.fact_bookings fb
		join fcs_class_time fct on fb.class_session_id = fct.class_session_id
		where fb.booking_time >= current_date - interval '30 days'
		group by fct.class_time_bucket
	)
	select *
	from attendance_analysis
	order by attendance_rate desc;

select * from gym_analytics.vw_time_slot_utilization;

-- #6: How does class time (morning, afternoon, evening) impact attendance rates among booked members?

create or replace view gym_analytics.vw_time_attendance_rate as
	with fcs_class_time as (
		select fcs.class_session_id,fcs.class_id, fcs.start_time, fcs.end_time, fcs.end_time - fcs.start_time, 
		case 
			when fcs.start_time::time >= '06:00:00' and fcs.start_time::time < '12:00:00' then 'morning'
			when fcs.start_time::time >= '12:00:00' and fcs.start_time::time < '16:30:00' then 'afternoon'
			when fcs.start_time::time >= '16:30:00' and fcs.start_time::time < '19:00:00' then 'evening'
			else 'closed'
		end as class_time_bucket
		from gym_analytics.fact_class_sessions fcs 
	),
	attendance_analysis as (
		select
			fct.class_time_bucket,
			count(*) as total_bookings,
		count(case when fb.is_attended = true then 1 end) as attended_bookings,
		count(case when fb.is_attended = true then 1 end)::float/nullif(count(*), 0) as attendance_rate
		from gym_analytics.fact_bookings fb
		join fcs_class_time fct
		on fb.class_session_id = fct.class_session_id
		where fb.booking_time >= CURRENT_DATE - interval '30 days'
		group by fct.class_time_bucket
	)
	select *
	from attendance_analysis
	order by attendance_rate desc;
	
select * from gym_analytics.vw_time_attendance_rate;

-- #7: Which class time slots achieve the highest average attendance and fill rate?

create or replace view gym_analytics.vw_average_utilization as
	with fcs_class_time as (
		select
			fcs.class_session_id, fcs.class_id, fcs.start_time, fcs.end_time,
			fcs.end_time - fcs.start_time as session_duration,
			case
				when fcs.start_time::time >= '06:00:00' and fcs.start_time::time < '12:00:00' then 'morning'
				when fcs.start_time::time >= '12:00:00' and fcs.start_time::time < '16:30:00' then 'afternoon'
				when fcs.start_time::time >= '16:30:00' and fcs.start_time::time < '21:00:00' then 'evening'
				else 'off_hours'
			END as class_time_bucket, fcs.fill_rate
		from gym_analytics.fact_class_sessions fcs
	),
	attendance_analysis as (
		select
			fct.class_time_bucket,
			count(*) as total_bookings,
			count(
				case
					when fb.is_attended = TRUE then 1
				END
			) as attended_bookings,
			round(
				count(
					case
						when fb.is_attended = TRUE then 1
					END
				)::numeric
				/
				nullif(count(*), 0),
				4
			) as attendance_rate,
			round(
				AVG(fct.fill_rate)::numeric, 2
			) as avg_fill_rate
		from gym_analytics.fact_bookings fb
		join fcs_class_time fct on fb.class_session_id = fct.class_session_id
		where fb.booking_time >= CURRENT_DATE - interval '30 days' and fct.class_time_bucket != 'off_hours'
		group by fct.class_time_bucket
	)
	select *
	from attendance_analysis
	order by attendance_rate desc;

-- Revenue

-- #8: Do premium-tier members generate higher revenue per user compared to other tiers?

create or replace view gym_analytics.vw_membership_per_capita_revenue as
	select 
		me.membership_tier,
		count(distinct me.member_id) as members,
		sum(pa.amount) as total_revenue,
		sum(pa.amount)::numeric / nullif(count(distinct me.member_id), 0) as revenue_per_user
	from gym_analytics.members me
	join gym_analytics.payments pa 
		on pa.member_id = me.member_id
	group by me.membership_tier
	order by revenue_per_user desc;

select * from gym_analytics.vw_membership_per_capita_revenue;

-- #9: Is trainer revenue influenced by their tenure (time since hire)?

create or replace view gym_analytics.vw_tenure_influence as
	select 
		(CURRENT_DATE - tr.hire_date) as tenure_days,
		sum(ts.rate_charged) as total_revenue
	from gym_analytics.trainers tr
	join gym_analytics.trainer_sessions ts 
		on tr.trainer_id = ts.trainer_id
	group by tr.trainer_id, tr.hire_date
	order by tenure_days;

select * from gym_analytics.vw_tenure_influence;

-- #10: Which class types generate the highest total and per-session revenue?

create or replace view gym_analytics.class_type_revenue as
	select 
		cl.class_type,
		sum(ts.rate_charged) as total_revenue,
		sum(ts.rate_charged) / nullif(count(distinct ts.session_id), 0) as revenue_per_session
	from gym_analytics.classes cl
	join gym_analytics.schedules sc 
		on cl.class_id = sc.class_id
	join gym_analytics.trainer_sessions ts 
		on ts.schedule_id = sc.schedule_id
	group by cl.class_type
	order by total_revenue desc;

select * from gym_analytics.class_type_revenue;