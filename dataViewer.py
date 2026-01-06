#!python
import csv
import sys
import argparse
import calendar
import datetime
import dateutil
from datetime import timedelta
#import IPython
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
#from tkinter import Tk, Button, Toplevel, Label
#from tkinter import *
import tkinter
from tkcalendar import Calendar
from matplotlib.backend_bases import key_press_handler
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg, NavigationToolbar2Tk)

newSolarExportable      = True
estYearlyPgeEscalation  = 0.04      # %
est2024PgeCost          = 5763.54   # Based on 2024 solar and usage using latest PGE E-TOU-D rate plan numbers
oldSolarYearlyProd      = 5732      # Based on 2024 solar production measured by our Emporia VUE system
nonExportLimit          = 5.0       # Based on rating of SMA 5000 Inverter used for NEM 1.0 application
#maxChargeRate           = 5.0       # Tesla Powerwall 3 has 5kW charge rate.  Franklin aPower is 8kW.

# Minumum daily PGE charge if we don't use at least accrue at least that much in grid import charges
pgeMinDailyDeliveryCharge = 0.39167 # Dollars, approx $12 per month

enphaseChargedLabel    = 'Stored in batteries (Wh)'
enphaseConsumedLabel   = 'Energy Consumed (Wh)'
enphaseDateLabel       = 'Date/Time'
enphaseDischargedLabel = 'Discharged from batteries (Wh)'
enphaseExportedLabel   = 'Exported to Grid (Wh)'
enphaseGeneratorLabel  = 'Consumed From Generator (Wh)'
enphaseImportedLabel   = 'Imported from Grid (Wh)'
enphaseSolarLabel      = 'Energy Produced (Wh)'

vueDateLabel  = 'Time Bucket (America/Los_Angeles)'
vueSolarLabel = 'Main panel-Solar/Generation-Solar inverter (kWhs)'
pgeData = []
vueData = []
enphaseData = []

# PGE Baseline Info 2024
# https://www.pge.com/en/account/rate-plans/how-rates-work/baseline-allowance.html#tabs-59f0a2f599-item-f6f6231a48-tab
BaselineTerritory = 'X'     # Our territory from PGE bill
BaselineSummer    = 9.8     # kWh/day
BaselineWinter    = 9.7     # kWh/day

# PGE Rate Data 2024
# https://www.pge.com/assets/pge/docs/account/rate-plans/residential-electric-rate-plan-pricing.pdf
RatePlans = {
    "E-TOU-C": {
        "Summer": {
            "Baseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                },
            "AboveBaseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                }
            },
        "Winter": {
            "Baseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                },
            "AboveBaseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                }
            }
        },
    "E-TOU-D": {
        "Summer": {
            "OffPeak":  0.43,
            "Peak":     0.57
            },
        "Winter": {
            "OffPeak":  0.44,
            "Peak":     0.48
            }
        },
    "E-ELEC": {
        "Summer": {
            "OffPeak":      0.38872,
            "PartialPeak":  0.44540,
            "Peak":         0.60728
            },
        "Winter": {
            "OffPeak":      0.33982,
            "PartialPeak":  0.35368,
            "Peak":         0.37577
            }
        }
    }

SelectedDay = None
root = None
matplotlib.use('TkAgg')

def select_nextDay():
    global SelectedDay, myHomeSolar
    SelectedDay = SelectedDay + datetime.timedelta(days=1)
    myHomeSolar.PlotOptions()

def select_prevDay():
    global SelectedDay, myHomeSolar
    SelectedDay = SelectedDay - datetime.timedelta(days=1)
    myHomeSolar.PlotOptions()

def select_nextMonth():
    global SelectedDay, myHomeSolar
    SelectedDay = datetime.datetime( year=SelectedDay.year,
                                     month=min(12,SelectedDay.month + 1),
                                     day=SelectedDay.day )
    myHomeSolar.PlotOptions()

def select_prevMonth():
    global SelectedDay, myHomeSolar
    SelectedDay = datetime.datetime( year=SelectedDay.year,
                                     month=max(1,SelectedDay.month - 1),
                                     day=SelectedDay.day )
    myHomeSolar.PlotOptions()

def select_date():
    def on_date_select(date):
        global SelectedDay
        SelectedDay = date
        print( f"SelectedDay={SelectedDay:%b %d, %Y}" )
        #ax.set_xlim(date, date + datetime.timedelta(days=1))
        myHomeSolar.PlotOptions()
        #plt.draw()
        top.destroy()

    #global root, myHomeSolar
    global SelectedDay, myHomeSolar
    top = tkinter.Toplevel(myHomeSolar)
    #top = tkinter.Toplevel(myHomeSolar)
    cal = Calendar(top, selectmode='day', date_pattern='yyyy-mm-dd',
                    year=SelectedDay.year, month=SelectedDay.month, day=SelectedDay.day)
    cal.pack()
    tkinter.Button(top, text="Select", command=lambda: on_date_select(cal.selection_get())).pack()

def isPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak
        if timeOfDay.weekday() >= 5:
            return False
        if timeOfDay.hour < 17 or timeOfDay.hour >= 20:
            return False
        return True
    # Other rate plans have peak hours 4pm to 9pm
    if timeOfDay.hour < 16 or timeOfDay.hour >= 21:
        return False
    return True

def isPartialPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak, No Partial Peak
        return False
    if ratePlan == 'E-TOU-C':
        # E-TOU-C Every day 4-9pm Peak, otherwise OffPeak, No Partial Peak
        return False
    if ratePlan == 'E-ELEC':
        # E-ELEC Partial Peak Every day 3pm-4pm and 9pm to midnight
        if timeOfDay.hour == 15 or timeOfDay.hour >= 21:
            return True
        return False
    return False

def isOffPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak, No Partial Peak
        return not isPeakTime( timeOfDay, 'E-TOU-D' )
    if ratePlan == 'E-TOU-C':
        # E-TOU-C Every day 4-9pm Peak, otherwise OffPeak, No Partial Peak
        return not isPeakTime( timeOfDay, 'E-TOU-C' )
    if ratePlan == 'E-ELEC':
        # E-ELEC Off Peak Every day midnight to 3pm
        if timeOfDay.hour < 15:
            return True
        return False
    return False

def isSummerTime( timeOfDay ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return True
    return False

def isWinterTime( timeOfDay ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return True
    return False

def isSummerPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isPeakTime( timeOfDay, ratePlan )
    return False

def isWinterPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isPeakTime( timeOfDay, ratePlan )
    return False

def isSummerPartialPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isPartialPeakTime( timeOfDay, ratePlan )
    return False

def isWinterPartialPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isPartialPeakTime( timeOfDay, ratePlan )
    return False

def isSummerOffPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isOffPeakTime( timeOfDay, ratePlan )
    return False

def isWinterOffPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isOffPeakTime( timeOfDay, ratePlan )
    return False

# class EnergyData
class EnergyData:
    """
    Used for representation of solar, battery and other energy data for a specific period of time.
    Includes PGE, enPhase, and Vue monitoring data including usage, solar production,
    charging, grid import, grid export, excess solar, etc.
    """
    def __init__( self, time=None, duration=None,
                pgeImport=None, pgeExport=None, pgeCost=None,
                vueImport=None, vueExport=None, vueSolar=None,
                enphaseImport=None, enphaseExport=None,
                enphaseProduced=None, enphaseConsumed=None,
                enphaseBattery=None, enphaseGenerator=None,
                enphaseCharged=None, enphaseDisCharged=None,
                gridCharging=None, newExcess=None, oldExcess=None ):
        self.TimeOfDay  = datetime.datetime(year=2000,month=1,day=1) if time == None else time
        self.Duration   = time.time(hour=1,minute=0,second=0) if time == None else time
        self.Battery       = enphaseBattery    # Battery charge kWh
        self.Charged       = enphaseCharged    # Battery charging this hour kWh
        self.DisCharged    = enphaseDisCharged # Battery used this hour kWh
        self.Consumed      = enphaseConsumed   # kWh
        self.OldSolar      = vueSolar          # kWh
        self.NewSolar      = enphaseProduced   # kWh
        self.Generator     = enphaseGenerator  # kWh
        self.EnphaseImport = enphaseImport     # kWh
        self.EnphaseExport = enphaseExport     # kWh
        self.PgeImport     = pgeImport         # Pge Grid import kWh
        self.PgeExport     = pgeExport         # Pge Grid Export kWh
        self.Cost          = pgeCost           # $
        self.VueImport     = vueImport         # Vue Grid import kWh
        self.VueExport     = vueExport         # Vue Grid Export kWh
        self.GridCharging  = gridCharging      # Grid Charging kWh
        self.NewExcess     = newExcess         # Excess New Solar kWh
        self.OldExcess     = oldExcess         # Excess Old Solar kWh

    def __str__( self ):
        if self.TimeOfDay is None:
            return f"Undefined TimeOfDay"
        output = f"{self.TimeOfDay}: "
        if self.Duration is not None:
            output += f"Dur={self.Duration}"
        if self.Consumed is not None:
            output += f", Consumed={self.Consumed:>6.2f}"
        if self.NewSolar is not None:
            output += f", NewSolar={self.NewSolar:>6.2f}"
        if self.OldSolar is not None:
            output += f", OldSolar={self.OldSolar:>6.2f}"
        if self.PgeImport is not None:
            output += f", PgeImport={self.PgeImport:>6.2f}"
        if self.PgeExport is not None:
            output += f", PgeExport={self.PgeExport:>6.2f}"
        if self.Charged is not None:
            output += f", Charged={self.Charged:>6.2f}"
        if self.DisCharged is not None:
            output += f", DisCharged={self.DisCharged:>6.2f}"
        if self.GridCharging is not None:
            output += f", GridCharging={self.GridCharging:>6.2f}"
        if self.Battery is not None:
            output += f", Battery={self.Battery:>6.2f}"
        if self.NewExcess is not None:
            output += f", NewExcess={self.NewExcess:>6.2f}"
        if self.OldExcess is not None:
            output += f", OldExcess={self.OldExcess:>6.2f}"
        if self.Cost is not None:
            output += f", Cost=${self.Cost:>6.2f}"
        return output

def getEarliestDateTime( items ):
    listItems = list(items)
    return min(listItems, key=lambda item: item.TimeOfDay)

def getLatestDateTime( items ):
    listItems = list(items)
    return max(listItems, key=lambda item: item.TimeOfDay)


# class HourlyProj
class HourlyProj:
    """
    Used to compute hour by hour projections of grid vs solar vs battery status
    Includes usage, solar production, charging, export, excess solar, etc.
    """
    def __init__( self, time=None, grid=0, usage=0, battery=0, batteryUsed=0, charging=0, gridCharging=0, newSolar=0, oldSolar=0, newExcess=0, oldExcess=0, export=0, cost=0 ):
        # Keep these values as the input conditions
        self.TimeOfDay = datetime.datetime(year=2000,month=1,day=1) if time == None else time
        self.Usage     = usage     # kWh
        self.NewSolar  = newSolar  # kWh
        self.OldSolar  = oldSolar  # kWh
        # These values get revised as we do hourly processing
        self.Grid      = grid      # Grid import kWh
        self.Export    = export    # Grid Export kWh
        self.Battery   = battery   # Hourly Battery charge kWh
        self.BatteryUsed= batteryUsed # Battery used this hour kWh
        self.Charging  = charging  # Charging kWh
        self.GridCharging = gridCharging  # Grid Charging kWh
        self.NewExcess = newExcess # Excess New Solar kWh
        self.OldExcess = oldExcess # Excess Old Solar kWh
        self.Cost      = cost      # $

    def __str__( self ):
        #return f"{self.TimeOfDay}: Cost={self.Cost:>6.2f}, Grid={self.Grid:>6.2f}, Charging={self.Charging:>6.2f}, GridCharging={self.GridCharging:>6.2f}, Battery={self.Battery:>6.2f}, Export={self.Export:>6.2f}" 
        return f"{self.TimeOfDay}: Usage={self.Usage:>6.2f}, NewSolar={self.NewSolar:>6.2f}, OldSolar={self.OldSolar:>6.2f}, Grid={self.Grid:>6.2f}, Export={self.Export:>6.2f}, Charging={self.Charging:>6.2f}, GridCharging={self.GridCharging:>6.2f}, Battery={self.Battery:>6.2f}, BatteryUsed={self.BatteryUsed:>6.2f}, NewExcess={self.NewExcess:>6.2f}, OldExcess={self.OldExcess:>6.2f}, Cost=${self.Cost:>6.2f}"

    # Arithmetic operators
    def __add__( self, other ):
        # Note: Battery does not get added
        result = HourlyProj( time=self.TimeOfDay, grid=self.Grid, usage=self.Usage, battery=self.Battery, charging=self.Charging, gridCharging=self.GridCharging,
                            newExcess=self.NewExcess, oldExcess=self.OldExcess,
                            newSolar=self.NewSolar, oldSolar=self.OldSolar,
                            batteryUsed=self.BatteryUsed, export=self.Export, cost=self.Cost )
        result.Grid        += other.Grid
        result.Usage       += other.Usage
        result.Charging    += other.Charging
        result.GridCharging+= other.GridCharging
        result.NewExcess   += other.NewExcess
        result.OldExcess   += other.OldExcess
        result.NewSolar    += other.NewSolar
        result.OldSolar    += other.OldSolar
        result.Export      += other.Export
        result.BatteryUsed += other.BatteryUsed
        result.Cost        += other.Cost
        result.TimeOfDay    = max( result.TimeOfDay, other.TimeOfDay )
        return result
    def __truediv__( self, other ):
        # Note: Battery and TimeOfDay do not get modified
        result = HourlyProj( time=self.TimeOfDay, grid=self.Grid, usage=self.Usage, battery=self.Battery, charging=self.Charging, gridCharging=self.GridCharging,
                            newExcess=self.NewExcess, oldExcess=self.OldExcess, newSolar=self.NewSolar, oldSolar=self.OldSolar,
                            batteryUsed=self.BatteryUsed, export=self.Export, cost=self.Cost )
        result.Grid     /= other
        result.Usage    /= other
        result.Charging /= other
        result.GridCharging /= other
        result.NewExcess/= other
        result.OldExcess/= other
        result.NewSolar /= other
        result.OldSolar /= other
        result.Export   /= other
        result.BatteryUsed /= other
        result.Cost     /= other
        return result
    def __mul__( self, other ):
        # Note: Battery and TimeOfDay do not get modified
        result = HourlyProj( time=self.TimeOfDay, grid=self.Grid, usage=self.Usage, battery=self.Battery, charging=self.Charging, gridCharging=self.GridCharging,
                            newExcess=self.NewExcess, oldExcess=self.OldExcess, newSolar=self.NewSolar, oldSolar=self.OldSolar,
                            batteryUsed=self.BatteryUsed, export=self.Export, cost=self.Cost )
        result.Grid     *= other
        result.Usage    *= other
        result.Charging *= other
        result.GridCharging *= other
        result.NewExcess*= other
        result.OldExcess*= other
        result.NewSolar *= other
        result.OldSolar *= other
        result.Export   *= other
        result.BatteryUsed *= other
        result.Cost     *= other
        return result

    def ApplyBatteryToGrid( self ):
        if self.Grid > 0 and self.Battery > 0:
            if self.Battery >= self.Grid:
                self.BatteryUsed = self.Grid
                self.Battery -= self.BatteryUsed
                self.Grid = 0
            else:
                self.Grid -= self.Battery
                self.BatteryUsed = self.Battery
                self.Battery = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ApplyGridToBattery( self, desiredCharge, options ):
        if self.Battery >= options.MaxBattery:
            return
        availCharge = max(0, options.MaxChargeRate - self.Charging)
        newCharge = min( desiredCharge, availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.GridCharging += newCharge
        self.Grid += newCharge / (options.Efficiency/100)
        if self.Grid < 0:
            print( f"ApplyGridToBattery Error: Negative grid usage must be applied as Export!\n{self}" )
 
    def ApplyNewSolarToBattery( self, options ):
        if self.NewExcess <= 0:
            return
        if self.Battery >= options.MaxBattery:
            return
        availCharge = self.NewExcess * options.Efficiency / 100
        newCharge = min( options.MaxChargeRate, availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.NewExcess = max( 0, self.NewExcess - newCharge / (options.Efficiency/100) )
 
    def ApplyOldSolarToBattery( self, options ):
        if self.OldExcess <= 0:
            return
        if self.Battery >= options.MaxBattery:
            return
        availCharge = self.OldExcess * options.Efficiency / 100
        newCharge = min( options.MaxChargeRate, availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.OldExcess = max( 0, self.OldExcess - newCharge / (options.Efficiency/100) )

    def ApplyOldSolarToGrid( self ):
        if self.Grid > 0 and self.OldExcess > 0:
            if self.OldExcess >= self.Grid:
                self.OldExcess -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.OldExcess
                self.OldExcess = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ApplyNewSolarToGrid( self ):
        if self.Grid > 0 and self.NewExcess > 0:
            if self.NewExcess >= self.Grid:
                self.NewExcess -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.NewExcess
                self.NewExcess = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ExportBatteryToGrid( self, maxExport, options ):
        if self.Battery <= 0:
            return
        availExport = max( self.Battery, maxExport, options.MaxOutput )
        newExport = max( nonExportLimit, self.Export + availExport )
        self.BatteryUsed = newExport - self.Export
        self.Battery -= self.BatteryUsed
        self.Export = newExport
 
    def ExportNewSolarToGrid( self ):
        availExport = min( self.NewExcess, nonExportLimit - self.Export )
        if availExport > 0:
            self.Export    += availExport
            self.NewExcess -= availExport

    def ExportOldSolarToGrid( self ):
        availExport = min( self.OldExcess, nonExportLimit - self.Export )
        if availExport > 0:
            self.Export    += availExport
            self.OldExcess -= availExport

    def DetermineCost( self, options, dailyTotal=0 ):
        ratePlan = options.RatePlan
        if ratePlan not in RatePlans:
            print( "Error: Rate Plan %s not supported!" % ratePlan )
            return 0
        if self.Grid < 0:
            print( f"DetermineCost Error: Negative grid usage must be applied as Export!\n{self}" )
            return 0
        kWh = self.Grid
        if ratePlan == "E-TOU-C":
            if isSummerPeakTime(self.TimeOfDay,ratePlan):
                if BaselineSummer > dailyTotal:
                    # BaselineTotel = 9.8
                    # dailyTotal = 8.2
                    # kWh = 2.0
                    # 1.6 kWh @ baseline
                    # .4 kWh above baseline
                    baselineUsage = min(kWh, BaselineSummer-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Summer"]["Baseline"]["Peak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["Peak"]
            elif isWinterPeakTime(self.TimeOfDay,ratePlan):
                if BaselineWinter > dailyTotal:
                    baselineUsage = min(kWh, BaselineWinter-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Winter"]["Baseline"]["Peak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["Peak"]
            elif isSummerPartialPeakTime(self.TimeOfDay,ratePlan):
                if BaselineSummer > dailyTotal:
                    baselineUsage = min(kWh, BaselineSummer-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Summer"]["Baseline"]["PartialPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["PartialPeak"]
            elif isWinterPartialPeakTime(self.TimeOfDay,ratePlan):
                if BaselineWinter > dailyTotal:
                    baselineUsage = min(kWh, BaselineWinter-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Winter"]["Baseline"]["PartialPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["PartialPeak"]
            elif isSummerOffPeakTime(self.TimeOfDay,ratePlan):
                if BaselineSummer > dailyTotal:
                    baselineUsage = min(kWh, BaselineSummer-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Summer"]["Baseline"]["OffPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["OffPeak"]
            elif isWinterOffPeakTime(self.TimeOfDay,ratePlan):
                if BaselineWinter > dailyTotal:
                    baselineUsage = min(kWh, BaselineWinter-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Winter"]["Baseline"]["OffPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["OffPeak"]
        elif ratePlan == "E-TOU-D":
            if isSummerPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["Peak"]
            elif isWinterPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["Peak"]
            elif isSummerOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["OffPeak"]
            elif isWinterOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["OffPeak"]
        elif ratePlan == "E-ELEC":
            if isSummerPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["Peak"]
            elif isWinterPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["Peak"]
            elif isSummerPartialPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["PartialPeak"]
            elif isWinterPartialPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["PartialPeak"]
            elif isSummerOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["OffPeak"]
            elif isWinterOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["OffPeak"]
        else:
            print( "Rate plan %s not supported!" % ratePlan )
        if options.NEM == '3.0':
            self.Cost -= self.Export * 0.06

#   Options for home solar projections
#   opt1 = Option( 'Tesla', 'E-ELEC', '1.0', 13.5, 5, 5600, 32000 )
class Option( tkinter.Toplevel ):
    def __init__( self, parent, vendor, ratePlan, nem, maxBattery, maxChargeRate, newSolarProd, systemCost, useGridCharging=0, efficiency=95 ):
        super().__init__(parent)
        self.Vendor       = vendor
        self.RatePlan     = ratePlan      # 'E-ELEC' or 'E-TOU-C' or 'E-TOU-D'
        self.NEM          = nem           # '1.0' or '3.0'
        self.MaxBattery   = maxBattery    # kWh
        self.MaxChargeRate= maxChargeRate # kWh
        self.Efficiency   = efficiency    # %
        self.UseGridCharging= useGridCharging
        self.NewSolarProd = newSolarProd  # Yearly kWh
        self.SystemCost   = systemCost    # $
        self.YearlyPgeCost= 0             # $
        self.PaybackYears = 0             # years
        self.TwentyFiveYearSavings = 0    # $
        self.Projections   = []
        #print( f"class Option: Created {self}" )
        # Set title, create figure and actors 
        plotTitle = f"{self.MaxBattery}kWh {self.Vendor} Battery, NewSolarProd={self.NewSolarProd}, RatePlan={self.RatePlan}, NEM={self.NEM}, UseGridCharging={self.UseGridCharging}"
        self.title(plotTitle)
        self.YearlyDataFrame = tkinter.Frame(self, height=40)
        self.DailyGraphFrame = tkinter.Frame(self, height=120)
        self.DailyDataFrame = tkinter.Frame(self, height=40)
        #self.fig = plt.figure( plotTitle, figsize=(12,4) )
        #self.axs = self.fig.subplots( 1, 1 )
        #self.day_ax = self.axs[0]
        #self.day_ax = self.axs
        self.fig = plt.figure( plotTitle, figsize=(12,4) )
        self.day_ax = self.fig.add_subplot()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.DailyGraphFrame)
        #self.toolbar = NavigationToolbar2Tk(self.canvas, self.DailyGraphFrame, pack_toolbar=False)
        self.bold14Font = tkinter.font.Font(self, size=14, weight=tkinter.font.BOLD)
        self.l1 = tkinter.Label(self.DailyDataFrame, text=f"Today's Cost=", font=self.bold14Font)
        self.l2 = tkinter.Label(self.DailyDataFrame, text=f", Usage=", font=self.bold14Font)
        self.l3 = tkinter.Label(self.DailyDataFrame, text=f", Solar=", font=self.bold14Font)
        self.l4 = tkinter.Label(self.DailyDataFrame, text=f", Grid Import=", font=self.bold14Font)
        self.l5 = tkinter.Label(self.DailyDataFrame, text=f", Grid Export=", font=self.bold14Font)
        self.l6 = tkinter.Label(self.DailyDataFrame, text=f", Rem Battery=", font=self.bold14Font)
        self.YearlyDataFrame.grid(row=0)
        self.DailyGraphFrame.grid(row=1)
        self.DailyDataFrame.grid(row=2)

    def __str__( self ):
        return f"RatePlan={self.RatePlan:>7}, NEM={self.NEM}, MaxBattery={self.MaxBattery}kWh, MaxChargeRate={self.MaxChargeRate}kW, Efficiency={self.Efficiency}, NewSolarProd={self.NewSolarProd}kWh\nSystemCost=${self.SystemCost:>6.2f}, YearlyPgeCost=${self.YearlyPgeCost:>6.2f}, PaybackYears={self.PaybackYears:>4.2f} yrs, 25YearSavings=${self.TwentyFiveYearSavings:>.2f}" 

    def ComputeYearlyCosts( self ):
        YearlyTotals = HourlyProj(battery=self.MaxBattery)
        for newHour in self.Projections:
            YearlyTotals = YearlyTotals + newHour
        self.YearlyPgeCost = YearlyTotals.Cost
        totalSavings = 0
        estFutureCostAsIs = est2024PgeCost
        estFutureCostOfOption = self.YearlyPgeCost
        for year in range(1,26):
            thisYearsSavings = estFutureCostAsIs - estFutureCostOfOption
            totalSavings += thisYearsSavings
            if self.PaybackYears == 0 and totalSavings >= self.SystemCost:
                self.PaybackYears = year + (1-(totalSavings-self.SystemCost)/thisYearsSavings)
            estFutureCostAsIs *= (1 + estYearlyPgeEscalation)
            estFutureCostOfOption *= (1 + estYearlyPgeEscalation)
        self.TwentyFiveYearSavings = totalSavings
        #print( f"Est Yearly PGE cost in 25 years={estFutureCostAsIs:$>6.2f}" )
        #print( f"Est Yearly Option cost in 25 years={estFutureCostOfOption:$>6.2f}" )
        tkinter.Label(self.YearlyDataFrame, text=f"SystemCost=${self.SystemCost:>.0f}", font=self.bold14Font ).grid( row=1, column=0 )
        tkinter.Label(self.YearlyDataFrame, text=f"YrlyPgeCost=${self.YearlyPgeCost:>.0f}", font=self.bold14Font ).grid( row=1, column=1 )
        tkinter.Label(self.YearlyDataFrame, text=f"PaybkYrs={self.PaybackYears:>.2f} yrs", font=self.bold14Font ).grid( row=1, column=2 )
        tkinter.Label(self.YearlyDataFrame, text=f"25YrSavings=${self.TwentyFiveYearSavings:>.0f}", font=self.bold14Font ).grid( row=1, column=3 )
        tkinter.Label(self.YearlyDataFrame, text=f"YrlyExcess={YearlyTotals.OldExcess+YearlyTotals.NewExcess:>.0f}kWh", font=self.bold14Font ).grid( row=1, column=4 )

    def GetDataForDay( self, month, day ):
        Time = []
        Usage = []
        Solar = []
        OldSolar = []
        Grid = []
        Export = []
        Battery = []
        batteryUsed = []
        Charging = []
        GridCharging = []
        Excess = []
        Cost = []
        for energyData in self.Projections:
            if energyData.TimeOfDay.month != month:
                continue
            if energyData.TimeOfDay.day != day:
                continue
            if energyData.TimeOfDay.minute != 30:    # Computed energyData times end in *:30:00
                continue
            if True:
                print( energyData )
            Time.append( energyData.TimeOfDay )
            Usage.append( energyData.Usage )
            Solar.append( energyData.NewSolar + energyData.OldSolar )
            OldSolar.append( energyData.OldSolar )
            Grid.append( energyData.Grid )
            Export.append( energyData.Export )
            Battery.append( energyData.Battery )
            batteryUsed.append( energyData.BatteryUsed )
            Charging.append( (energyData.Charging-energyData.GridCharging) / (self.Efficiency/100) )
            GridCharging.append( energyData.GridCharging / (self.Efficiency/100) )
            Excess.append( energyData.NewExcess + energyData.OldExcess )
            Cost.append( energyData.Cost )
        data = {    'TimeOfDay':    np.array(Time),
                    'Usage':        np.array(Usage),
                    'solar':        np.array(Solar),
                    'oldSolar':     np.array(OldSolar),
                    'export':       np.array(Export),
                    'battery':      np.array(Battery),
                    'batteryUsed':  np.array(batteryUsed),
                    'charging':     np.array(Charging),
                    'gridCharging': np.array(GridCharging),
                    'excess':       np.array(Excess),
                    'cost':         np.array(Cost),
                    'grid':         np.array(Grid) }
        return data

    def PlotDay( self, month, day ):
        '''
        Option:PlotDay( self, month, day )
        '''
        #print( f"PlotDay: {month}/{day} for Option {self}" )
        data = self.GetDataForDay( month, day )
        if False:
            print( f"{month}/{day} data:         {data}" )
        if newSolarExportable:
            gridBottom = data['solar'] + data['batteryUsed']
        else:
            gridBottom = data['oldSolar'] + data['batteryUsed']
        self.day_ax.set_yticks( np.arange(int(max(max(data['solar']),max(data['Usage']),max(data['grid'] + data['solar'] + data['batteryUsed']))+0.99999)+1) )
        #print( "max solar=", max(data['solar']) )
        #print( "int max solar=", int(max(data['solar'])+0.9) )
        #print( "yticks range=", np.arange(int(max(data['solar'])+0.9)) )
        self.day_ax.set_title(f"NewSolar={self.NewSolarProd}kWh, Battery={self.MaxBattery:.1f}kWh, Grid Usage Solar and Battery for {month}/{day}",
                            fontsize=16, fontweight='bold' )
        self.day_ax.plot( 'TimeOfDay', 'Usage', data=data, color='xkcd:pale orange' )
        self.day_ax.plot( 'TimeOfDay', 'solar', data=data, color='xkcd:bright yellow', label='Solar Prod' )
        gridBottom = data['solar'] + data['batteryUsed']
        self.day_ax.bar( 'TimeOfDay', 'grid', data=data, color='xkcd:orange', width=timedelta(minutes=34), align='center', label='Grid', bottom=gridBottom )
        self.day_ax.bar( 'TimeOfDay', 'solar', data=data, color='xkcd:bright yellow', width=timedelta(minutes=34), align='center', label='Solar' )
        #batteryBottom = data['Usage'] - data['batteryUsed']
        batteryBottom = data['solar'] - data['excess'] - data['export'] - data['charging']
        self.day_ax.bar( 'TimeOfDay', 'batteryUsed', data=data, color='xkcd:cobalt blue', width=timedelta(minutes=34), align='center', label='Battery', bottom=batteryBottom)
        #chargingBottom = data['solar'] - data['batteryUsed']
        chargingBottom = data['Usage'] - data['batteryUsed']
        self.day_ax.bar( 'TimeOfDay', 'charging', data=data, color='xkcd:sky blue', width=timedelta(minutes=28), align='center', label='Charging', bottom=chargingBottom )
        #gridChargingBottom = data['charging'] - data['gridCharging']
        gridChargingBottom = data['Usage'] + data['charging'] - (data['gridCharging']/self.Efficiency)
        self.day_ax.bar( 'TimeOfDay', 'gridCharging', data=data, color='xkcd:electric blue', width=timedelta(minutes=14), align='center', label='GridCharging', bottom=gridChargingBottom )
        exportBottom = data['solar'] - data['excess'] - data['export']
        self.day_ax.bar( 'TimeOfDay', 'export', data=data, color='xkcd:fire engine red', width=timedelta(minutes=14), align='center', label='Export', bottom=exportBottom)
        excessBottom = data['solar'] - data['excess']
        self.day_ax.bar( 'TimeOfDay', 'excess', data=data, color='xkcd:neon purple', width=timedelta(minutes=14), align='center', label='Excess', bottom=excessBottom)

        self.day_ax.legend(loc='upper left')
        self.l1.config( text=f"Today's Cost=${sum(data['cost']):>6.2f}" )
        self.l2.config( text=f", Usage={sum(data['Usage']):>2.1f}kWh" )
        self.l3.config( text=f", Solar={sum(data['solar']):>2.1f}kWh" )
        self.l4.config( text=f", Grid Import={sum(data['grid']):>2.1f}kWh" )
        self.l5.config( text=f", Grid Export={sum(data['export']):>2.1f}kWh" )
        self.l6.config( text=f", Rem Battery={data['battery'][-1]:>2.1f}kWh" )
        self.l1.grid( row=2, column=0 )
        self.l2.grid( row=2, column=1 )
        self.l3.grid( row=2, column=2 )
        self.l4.grid( row=2, column=3 )
        self.l5.grid( row=2, column=4 )
        self.l6.grid( row=2, column=5 )

        #self.canvas.draw()

    def PlotOption( self ):
        global SelectedDay, root, myHomeSolar
        #self.fig.clf()
        w1 = self.canvas.get_tk_widget()
        if w1 is None:
            return
        if not w1.winfo_exists():
            return
        self.day_ax.cla()
        #self.plotWindow = tkinter.Toplevel(root)
        self.day_ax.xaxis.set_major_locator(mdates.HourLocator())
        self.day_ax.xaxis.set_major_formatter(mdates.DateFormatter('%I%p'))
        plt.setp( self.day_ax.xaxis.get_majorticklabels(), rotation=45 )
        #self.day_ax.set_xticks(rotation=45)
        self.day_ax.set_xlabel('Time')
        self.day_ax.set_ylabel('kWh')
 
        #self.toolbar.update()
        #self.toolbar.grid(row=0)
        #w1.grid(row=0)
        w1.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=True)

        # Plot data for selected day
        if True:
            print( f"PlotOption: {self}" )
        self.PlotDay( SelectedDay.month, SelectedDay.day )
        #self.plotWindow.grab_set()
        self.canvas.draw()

def DebugPeakVsOffPeakTimes( timeOfDay ):
    debugWinter2Summer = datetime.datetime( year=timeOfDay.year, month=6, day = 1 )
    debugSummer2Winter = datetime.datetime( year=timeOfDay.year, month=10, day = 1 )
    debugInterval = timedelta(days=1) 
    if (   abs(timeOfDay - debugSummer2Winter) <= debugInterval
        or abs(timeOfDay - debugWinter2Summer) <= debugInterval ):
        dataHour = timeOfDay.hour
        if dataHour >= 14:
            return True
    return False

def DebugThisDay( timeOfDay, year, month, day ):
    if timeOfDay.year == year and timeOfDay.month == month and timeOfDay.day == day:
        return True
    return False

class HomeSolar(tkinter.Tk):
    def __init__( self ):
        super().__init__()
        self.title('Main Window')
        self.energyData = {}
        self.options = []
        plt.style.use('bmh')
        self.geometry( '300x200' )
 
        #button_ax = plt.axes([0.8, 0.05, 0.1, 0.075])
        selectButton    = tkinter.Button(master=self, text='Select Date', command=select_date)
        nextDayButton   = tkinter.Button(master=self, text='Next Day',    command=select_nextDay)
        prevDayButton   = tkinter.Button(master=self, text='Prev Day',    command=select_prevDay)
        nextMonthButton = tkinter.Button(master=self, text='Next Month',  command=select_nextMonth)
        prevMonthButton = tkinter.Button(master=self, text='Prev Month',  command=select_prevMonth)
        selectButton.grid(  row=1, column=1, columnspan=2, sticky="" )
        prevDayButton.grid( row=2, column=1 )
        nextDayButton.grid( row=2, column=2 )
        prevMonthButton.grid( row=3, column=1 )
        nextMonthButton.grid( row=3, column=2 )
        self.columnconfigure( 1, uniform=1 )
        self.columnconfigure( 2, uniform=1 )
        #button = Button(button_ax, text='Select Date', color='xkcd:celery')

    def PlotOptions( self ):
        # plt.clf() breaks plotting
        for option in self.options:
            option.PlotOption()

    def AddOption( self, option, verbose=False ):
        global SelectedDay
        self.options.append( option )
        if verbose:
            print( f'\nAdding option: {option}' )
        battery = option.MaxBattery / 2
        earliestDateTime = getEarliestDateTime( self.energyData )
        option.Projections.append( HourlyProj( time=earliestDateTime, battery=battery ) )
        diagTotals = HourlyProj()
        diagDay  = HourlyProj()
        verboseDay = False
        SelectedDay = datetime.datetime(    year=earliestDateTime.year,
                                            month=earliestDateTime.month,
                                            day=earliestDateTime.day )
        priorDay = 0
        priorDayPeakUsage = 0
        priorDayPartialPeakUsage = 0
        priorDayGridChargingUsed = 0
        dailyTotal = 0
        dailyPeakUsage = 0
        dailyPartialPeakUsage = 0
        sortedData = list(self.energyData).sort(key=lambda data: data.TimeOfDay)
        for data in sortedData:
            oldSolar = -data.SolarProd
            if oldSolar < 0.02: oldSolar = 0 # Clean up output by eliminating trivial solar kWh due to CT accuracy limits
            newSolar = oldSolar * (option.NewSolarProd / oldSolarYearlyProd)

            if  priorDay != data.TimeOfDay.day:
                # Housekeeping for each new day
                priorDay = data.TimeOfDay.day
                dailyTotal = 0
                decayFactor = 0.60
                priorDayPeakUsage = (priorDayPeakUsage*decayFactor) + (dailyPeakUsage*(1.0-decayFactor))
                priorDayPartialPeakUsage = (priorDayPartialPeakUsage*decayFactor) + (dailyPartialPeakUsage*(1.0-decayFactor))
                #priorDayPeakUsage = dailyPeakUsage
                #priorDayPartialPeakUsage = dailyPartialPeakUsage
                dailyPeakUsage = 0
                dailyPartialPeakUsage = 0
                priorDayGridChargingUsed = priorDayGridChargingUsed*(1.0-decayFactor) + diagDay.GridCharging
                if battery < 0.15:
                    priorDayGridChargingUsed = 0
                if verboseDay:
                    print( f"DiagDay:\n{diagDay}" )
                diagDay = HourlyProj(time=data.TimeOfDay)
 
            verboseDay = DebugThisDay( data.TimeOfDay, SelectedDay.year, SelectedDay.month, SelectedDay.day )

            newHour = HourlyProj( time=data.TimeOfDay, grid=data.Usage, usage=data.Usage, battery=battery,
                                oldExcess=oldSolar, newExcess=newSolar, oldSolar=oldSolar, newSolar=newSolar )
            #if verboseDay: print( newHour )
            if isPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle Peak periods
                #
                dailyPeakUsage += newHour.Usage
                if option.NEM == '1.0':
                    # Battery then Solar
                    newHour.ApplyBatteryToGrid( )
                    newHour.ApplyNewSolarToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                else:
                    # Use NewSolar first
                    newHour.ApplyNewSolarToGrid( )
                    # OldSolar then Battery
                    newHour.ApplyOldSolarToGrid( )
                    newHour.ApplyBatteryToGrid( )
            elif isPartialPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle PartialPeak periods
                #
                dailyPartialPeakUsage += newHour.Usage
                if option.NEM == '1.0':
                    # Only use battery for 3-4pm partial peak if we can cover peak usage too
                    if data.TimeOfDay.hour != 15 or newHour.Battery >= (data.Usage + priorDayPeakUsage):
                        # During Winter, partialPeak rate is less than offPeakRate/batteryEfficiency,
                        # so using grid charged battery would be more expensive
                        if isSummerTime(data.TimeOfDay) or ((priorDayGridChargingUsed+diagDay.GridCharging) < 0.2) or newHour.Battery > 3:
                            newHour.ApplyBatteryToGrid( )
                    newHour.ApplyNewSolarToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                else:
                    newHour.ApplyNewSolarToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                    # Only use battery if we can cover peak usage too
                    if data.TimeOfDay.hour != 15 or newHour.Battery >= (data.Usage + priorDayPeakUsage):
                        # During Winter, partialPeak rate is less than offPeakRate/batteryEfficiency,
                        # so using grid charged battery would be more expensive
                        if isSummerTime(data.TimeOfDay) or ((priorDayGridChargingUsed+diagDay.GridCharging) < 0.2) or newHour.Battery > 3:
                            newHour.ApplyBatteryToGrid( )
            elif isOffPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle OffPeak periods
                #
                #newHour.ApplyNewSolarToGrid( )
                newHour.ApplyOldSolarToGrid( )
                newHour.ApplyNewSolarToGrid( )

                newHour.ApplyNewSolarToBattery( option )
                if option.NewSolarProd == 0 or option.NEM == '3.0':
                    # If we add new solar under NEM 1.0 via non-export, 
                    # we can only charge the battery from NewSolar
                    newHour.ApplyOldSolarToBattery( option )

                if data.TimeOfDay.hour <= 9 and (priorDayGridChargingUsed+diagDay.GridCharging) < 0.1:
                    # and data.TimeOfDay.month < 11 and data.TimeOfDay.month > 2 ):
                    # Apply remaining battery to grid
                    newHour.ApplyBatteryToGrid( )

            # Use grid charging if battery wouldn't otherwise get fully charged
            if option.UseGridCharging and isOffPeakTime(data.TimeOfDay,option.RatePlan):
                # Determine how much battery charge we need to cover Peak hours and Summer PartialPeak hours
                minBatteryChargeForPeak = priorDayPeakUsage if isWinterTime(data.TimeOfDay) else priorDayPeakUsage + priorDayPartialPeakUsage
                # Subtract ?% as we don't want to use grid charging more than needed as we lose money then.
                #minBatteryChargeForPeak *= 0.8
                minBatteryStateOfCharge = 10.0
                minBatteryChargeForPeak = minBatteryStateOfCharge
                desiredGridCharge = max(0, minBatteryChargeForPeak - newHour.Battery)
                availableCharging = min( option.MaxBattery-newHour.Battery, option.MaxChargeRate-newHour.Charging )
                if  desiredGridCharge > availableCharging:
                    desiredGridCharge = availableCharging
                laterCharging = option.MaxChargeRate*max(0,14-data.TimeOfDay.hour)
                if desiredGridCharge > (laterCharging + 1.0):
                    print( f"{newHour.TimeOfDay}: desiredGridCharge={desiredGridCharge:.2f}, availableCharging={availableCharging:.2f}, Battery={newHour.Battery:.2f}, minBatteryChargeForPeak={minBatteryChargeForPeak:.2f}, priorDayPeakUsage={priorDayPeakUsage:.2f}" )
                    newHour.ApplyGridToBattery( desiredGridCharge, option )

            # Export excess solar to grid
            newHour.ExportOldSolarToGrid( )
            if newSolarExportable or option.NEM == '3.0':
                newHour.ExportNewSolarToGrid( )
            newHour.TimeOfDay += timedelta( minutes=30 )

            # Apply remaining peak or partial peak NewSolar to battery
            newHour.ApplyNewSolarToBattery( option )
 
            # Determine costs for this hour
            newHour.DetermineCost( option, dailyTotal )

            # Hold remaining battery for next hour
            battery = newHour.Battery
            diagTotals += newHour
            diagDay    += newHour
            if verboseDay:
                print( newHour )

            # Add newHour to computed projections
            option.Projections.append( newHour )

        # Compute yearly costs, paypack period, and 25 year savings
        option.ComputeYearlyCosts()

        print( f'Projections for: {option}\n' )

        if True and (diagTotals.Grid or diagTotals.Charging or diagTotals.Export):
            print( f"DiagTotals:         {diagTotals}" )

        if not verbose:
            return

        # Compute average hourly data for Summer, Winter, and diagMonth
        diagMonth = 8
        diagMonthDays = None
        priorDay = 0
        YearlyTotals            = HourlyProj(battery=option.MaxBattery)
        SummerTotals            = HourlyProj(battery=option.MaxBattery)
        SummerPeakTotals        = HourlyProj(battery=option.MaxBattery)
        SummerPartialPeakTotals = HourlyProj(battery=option.MaxBattery)
        SummerOffPeakTotals     = HourlyProj(battery=option.MaxBattery)
        WinterTotals            = HourlyProj(battery=option.MaxBattery)
        WinterPeakTotals        = HourlyProj(battery=option.MaxBattery)
        WinterPartialPeakTotals = HourlyProj(battery=option.MaxBattery)
        WinterOffPeakTotals     = HourlyProj(battery=option.MaxBattery)
        diagMonthTotals         = HourlyProj(battery=option.MaxBattery)
        for newHour in option.Projections:
            YearlyTotals = YearlyTotals + newHour
            if isSummerTime( newHour.TimeOfDay ):
                SummerTotals = SummerTotals + newHour
            if isSummerPeakTime( newHour.TimeOfDay, option.RatePlan ):
                SummerPeakTotals = SummerPeakTotals + newHour
            if isSummerPartialPeakTime( newHour.TimeOfDay, option.RatePlan ):
                SummerPartialPeakTotals = SummerPartialPeakTotals + newHour
            if isSummerOffPeakTime( newHour.TimeOfDay, option.RatePlan ):
                SummerOffPeakTotals += newHour
            if isWinterTime( newHour.TimeOfDay ):
                WinterTotals += newHour
            if isWinterPeakTime( newHour.TimeOfDay, option.RatePlan ):
                WinterPeakTotals += newHour
            if isWinterPartialPeakTime( newHour.TimeOfDay, option.RatePlan ):
                WinterPartialPeakTotals += newHour
            if isWinterOffPeakTime( newHour.TimeOfDay, option.RatePlan ):
                WinterOffPeakTotals += newHour
            if newHour.TimeOfDay.month == diagMonth:
                diagMonthTotals += newHour
                if not diagMonthDays:
                    diagMonthFirstDay, diagMonthDays = calendar.monthrange( newHour.TimeOfDay.year, diagMonth )
        SummerAvg            = SummerTotals / (365 * 4 / 12)
        SummerPeakAvg        = SummerPeakTotals / (365 * 4 / 12)
        SummerPartialPeakAvg = SummerPartialPeakTotals / (365 * 4 / 12)
        SummerOffPeakAvg     = SummerOffPeakTotals / (365 * 4 / 12)
        WinterAvg            = WinterTotals / (365 * 8 / 12)
        WinterPeakAvg        = WinterPeakTotals / (365 * 8 / 12)
        WinterPartialPeakAvg = WinterPartialPeakTotals / (365 * 8 / 12)
        WinterOffPeakAvg     = WinterOffPeakTotals / (365 * 8 / 12)
        diagMonthAvg         = diagMonthTotals / diagMonthDays
        print( f"Yearly      Totals: {YearlyTotals}" )
        print( f"Summer      Totals: {SummerTotals}" )
        print( f"Summer Peak Totals: {SummerPeakTotals}" )
        print( f"Summer PaPk Totals: {SummerPartialPeakTotals}" )
        print( f"Summer OffP Totals: {SummerOffPeakTotals}" )
        print( f"Summer         Avg: {SummerAvg}" )
        print( f"Summer Peak    Avg: {SummerPeakAvg}" )
        print( f"Summer PaPk    Avg: {SummerPartialPeakAvg}" )
        print( f"Summer OffP    Avg: {SummerOffPeakAvg}" )

        print( f"Winter      Totals: {WinterTotals}" )
        print( f"Winter         Avg: {WinterAvg}" )
        print( f"Winter Peak    Avg: {WinterPeakAvg}" )
        print( f"Winter PaPk    Avg: {WinterPartialPeakAvg}" )
        print( f"Winter OffPeak Avg: {WinterOffPeakAvg}" )
        print( f"{calendar.month_name[diagMonth]}     Totals: {diagMonthTotals}" )

    def CombineDataFiles( self, pgeData, enphaseData, vueData, verbose = False ):
        # Note: Both data files have 23 entries for start of DST, 3/10/24
        # pgeData has 24 entries for DST, 11/3/24
        # vueData has 25 entries, but we add 1 min to the duplicate 1:00 am as
        # 11/3/24 actually lasts for 25 hours.
        # vueData also includes an extra entry for midnight on the day after the last export day
        # i.e.  Exporting 1/1/24 to 12/31/24 includes an entry for 1/1/25 00:00
        usage = 0
        extraHour  = datetime.datetime(year=2000,month=1,day=1)
        if len(vueData) > 0:
            extraHour = vueData[-1].TimeOfDay.hour
        # Start w/ vueData as it has the most attributes.
        # vueData has one attribute for each monitored circuit in both main panel and subpanel 
        for d in vueData:
            self.energyData[d.TimeOfDay] = d
        
        # Add pgeData
        for d in pgeData:
            if d.TimeOfDay in self.energyData:
                self.energyData[d.TimeOfDay].pgeInput = d.pgeInput
                self.energyData[d.TimeOfDay].pgeOutput = d.pgeOutput
                self.energyData[d.TimeOfDay].pgeCost = d.pgeCost
            if d.TimeOfDay in pgeData:
                usage = pgeData[hourTime]
            # solarProd is negative and needs to be combined
            # with PGE usage to reflect actual usage w/o solar
            usage = max( 0, usage - solarProd )
            if hourTime < extraHour:
                self.energyData[hourTime] = EnergyData( usage, solarProd, hourTime )
        if verbose:
            earliestDateTime = getEarliestDateTime( self.energyData )
            latestDateTime = getLatestDateTime( self.energyData )
            print( 'Processed %u hourly usage and solarProd values.' % len(self.energyData) )
            print( 'From %s to %s' % ( earliestDateTime.strftime('%m/%d/%Y, %H:%M'),
                                       latestDateTime.strftime('%m/%d/%Y, %H:%M') ) )

def readPgeData( pgeDataFile, verbose=False ):
    newPgeData = []
    try:
        if verbose:
            print( "readPgeData: Reading %s" % pgeDataFile )
        in_file = open( pgeDataFile, 'r' )
        nameLine = in_file.readline()
        if nameLine.find('Name') < 0:
            nameLine = in_file.readline()
        if nameLine.find('Name') < 0:
            print( '2nd line in PGE Data File should be Name of acct owner, not\n%s\n' % nameLine )
        addrLine = in_file.readline()
        if addrLine.split(',')[0] != 'Address':
            print( '3rd line in PGE Data File should be Address of acct owner, not\n%s\n' % addrLine )
        acctLine = in_file.readline()
        if acctLine.split(',')[0] != 'Account Number':
            print( '4th line in PGE Data File should be Account Number, not\n%s\n' % acctLine )
        svcLine  = in_file.readline()
        if svcLine.split(',')[0] != 'Service':
            print( '5th line in PGE Data File should be Service, not\n%s\n' % svcLine )
        blankLine = in_file.readline()

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (pgeDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

    csv_reader = csv.DictReader(in_file)

    numRows = 0
    pgeImport = 0
    pgeExport = 0
    pgeCost = 0
    rowTime = datetime.datetime.now()
    for row in csv_reader:
        numRows  = numRows+1
        rowDate  = dateutil.parser.parse( row['DATE'] )
        rowStart = dateutil.parser.parse( row['START TIME'] )
        rowEnd   = dateutil.parser.parse( row['END TIME'] )
        pgeCost  = float(row['COST'].replace('$',''))
        if 'USAGE (kWh)' in csv_reader.fieldnames:
            pgeImport = float( row['USAGE (kWh)'])
            pgeExport = 0.0
        else:
            pgeImport = float( row['IMPORT (kWh)'])
            pgeExport = float( row['EXPORT (kWh)'])

        rowTime  = rowDate + datetime.timedelta(hours=rowStart.hour, minutes=rowStart.minute)
        duration = rowEnd + datetime.timedelta(minutes=1) - rowStart
        if rowTime in newPgeData:
            rowTime = rowTime + datetime.timedelta(minutes=1)
        newPgeData.append( EnergyData(time=rowTime, duration=duration, pgeImport=pgeImport, pgeExport=pgeExport, pgeCost=pgeCost) )
        if verbose and len(newPgeData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), pgeImport ) )
    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), pgeImport ) )

    return newPgeData

def readVueData( vueDataFile, verbose=False ):
    newVueData = []
    if verbose:
        print( "readVueData: Reading %s" % ( vueDataFile ) )
    try:
        in_file = open( vueDataFile, 'r' )

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (vueDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

    csv_reader = csv.DictReader(in_file)
    numRows = 0
    solarOutput = 0
    rowTime  = datetime.datetime.now()
    duration = datetime.timedelta(minutes=15)
    for row in csv_reader:
        rowTime = dateutil.parser.parse( row[vueDateLabel] )
        if numRows == 1:
            duration = rowTime - newVueData[0].TimeOfDay
            newVueData[0].duration = duration
        if vueSolarLabel in csv_reader.fieldnames:
            solarOutput = float( row[vueSolarLabel])
        # TODO: Handle dups
        #if rowTime in newVueData:
        #   rowTime = rowTime + datetime.timedelta(minutes=1)
        newVueData.append( EnergyData(time=rowTime, duration=duration, vueSolar=solarOutput ) )
        if verbose and len(newVueData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
        numRows = numRows+1

    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
    return newVueData

def readEnphaseData( enphaseDataFile, verbose=False ):
    newEnphaseData = []
    if verbose:
        print( "readEnphaseData: Reading %s" % ( enphaseDataFile ) )
    try:
        in_file = open( enphaseDataFile, 'r' )

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (enphaseDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

    csv_reader = csv.DictReader(in_file)
    numRows = 0
    rowTime  = datetime.datetime.now()
    duration = datetime.timedelta(minutes=15)
    solarOutput = 0
    for row in csv_reader:
        rowTime = dateutil.parser.parse( row[enphaseDateLabel] )
        if numRows == 1:
            duration = rowTime - newEnphaseData[0].TimeOfDay
            newEnphaseData[0].duration = duration
        if enphaseSolarLabel in csv_reader.fieldnames:
            solarOutput = float( row[enphaseSolarLabel])
        # TODO: Handle dups
        #if rowTime in newEnphaseData:
        #    rowTime = rowTime + datetime.timedelta(minutes=1)
        newEnphaseData.append( EnergyData(time=rowTime, duration=duration, enphaseProduced=solarOutput ) )
        if verbose and len(newEnphaseData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
        numRows = numRows+1

    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
    return newEnphaseData

def process_options(argv):
    if argv is None:
       argv = sys.argv[1:]
    desc = 'dataViewer reads PGE, Enphase, and Emporia Vue data files and creates screens to view the data.'
    parser = argparse.ArgumentParser( description = desc )
    parser.add_argument( '-f', '--pgeDataFiles', dest='pgeDataFiles', nargs="*", \
            help='Read PGE Data File -f pgeDataFile1.csv [-f pgeDataFile2.csv]' )
    parser.add_argument( '-V', '--vueDataFiles', dest='vueDataFiles', nargs="*", \
            help='Read Emporia Vue data file.' )
    parser.add_argument( '-e', '--enphaseDataFiles', dest='enphaseDataFiles', nargs="*", \
            help='Read Enphase data file.' )
    parser.add_argument( '-v', '--verbose', action='store_true', help='show verbose diags' )
    options = parser.parse_args()
    return options

# Create myHomeSolar
myHomeSolar = None

def main(argv=None):
    options = process_options(argv)

    global pgeData
    if options.pgeDataFiles:
        for pgeDataFile in options.pgeDataFiles:
            newData = readPgeData( pgeDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" PGE Data Points' % len(newData) )
            pgeData.extend(newData)

    if options.verbose and len(pgeData) > 0:
        print( 'Total "%u" PGE Data Points' % len(pgeData) )
        print( 'From %s to %s' % ( pgeData[0].TimeOfDay.strftime('%m/%d/%Y, %H:%M'),
                                   pgeData[-1].TimeOfDay.strftime('%m/%d/%Y, %H:%M') ) )

    global enphaseData
    if options.enphaseDataFiles:
        for enphaseDataFile in options.enphaseDataFiles:
            newData = readEnphaseData( enphaseDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" Enphase Data Points' % len(newData) )
            enphaseData.extend(newData)

    if options.verbose and len(enphaseData) > 0:
        print( 'Total "%u" Enphase Data Points' % len(enphaseData) )
        print( 'From %s to %s' % ( enphaseData[0].TimeOfDay.strftime('%m/%d/%Y, %H:%M'),
                                   enphaseData[-1].TimeOfDay.strftime('%m/%d/%Y, %H:%M') ) )

    global vueData
    if options.vueDataFiles:
        for vueDataFile in options.vueDataFiles:
            newData = readVueData( vueDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" VUE Data Points' % len(newData) )
            vueData.extend(newData)

    if options.verbose and len(vueData) > 0:
        print( 'Total "%u" VUE Data Points' % len(vueData) )
        print( 'From %s to %s' % ( vueData[0].TimeOfDay.strftime('%m/%d/%Y, %H:%M'),
                                   vueData[-1].TimeOfDay.strftime('%m/%d/%Y, %H:%M') ) )

    global myHomeSolar
    myHomeSolar = HomeSolar()
    myHomeSolar.CombineDataFiles( pgeData, enphaseData, vueData, options.verbose )

    #print("Current PGE Rate Plan Costs")
    #myHomeSolar.AddOption( Option( myHomeSolar, 'None', 'E-TOU-D', '1.0', 0, 0, 0, 0 ), verbose=options.verbose )
    #print("\nNEM 1.0 options")

    # Enphase Inverters w/ 3 Enphase 5P Batteries
    #myHomeSolar.AddOption( Option( myHomeSolar, 'Enphase-3x5P', 'E-ELEC', '1.0', 5.0*3, 3.2*3, 14215+672*-0, (52000+1250*-0)*0.70, useGridCharging=0, efficiency=90), verbose=options.verbose )

    # Get handle for Tkinter root window and hide it
    #global root
    #root = tkinter.Tk()
    #root.withdraw()

    # Plot each option
    myHomeSolar.PlotOptions()

    #fig = plt.figure( "Solar and Battery Analysis", figsize=(14,40) )
    #ax = plt.subplot( 1, 2, 1 )

    #plt.show()
    myHomeSolar.mainloop()
    #print( "Starting IPython shell..." )
    #IPython.embed()
    return 0

if __name__ == '__main__':
    status = main()
    sys.exit(status)

