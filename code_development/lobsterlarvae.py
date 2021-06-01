# This file is intended for Jasus edwardsii and has been adapted from bivalvelarvae.py and larvalfish.py 
# It introduces a multi-step dispersal phase based on the development of the lobster larvae: nauplosioma, phyllosoma, and puerulus
# . Nauplosioma stage: lobster larvae hatch into this stage and rise to the surface where they metamorphose into phyllosoma. Brief stage (<12hrs) that is not represented in this code, but can be implied by the release of larvae slightly offshore and at the surface  
# . Phyllosoma stage: planktonic stage where larvae can control their vertical position in the water column via buoyancy. This stage is characterized by diel vertical migration. Rarely found inshore after the stage 5, so we remove phyllosoma larvae found within 20 km of the coast 4 to 12 mo after hatching.
# . Puerulus stage: at this stage the lobster larvae have developed horizontal swimming capabilities and if close enough to the coast will swim to their settlement habitat. The pueruli have poorly developed mouth and rely on stored energy for the final stretch of their dispersal.
# 
#  Authors : Romain Chaput
# 
# 
#  Under development - more testing to do



import numpy as np
from opendrift.models.oceandrift import OceanDrift, Lagrangian3DArray
import logging; logger = logging.getLogger(__name__)
import shapefile # added for settlement in polygon only
from shapely.geometry import Polygon, Point, MultiPolygon # added for settlement in polygon only
import numba
import pymap3d as pm
import fiona


# Defining the  element properties from Pelagicegg model
class LobsterLarvaeObj(Lagrangian3DArray):
    """Extending Lagrangian3DArray with specific properties for pelagic eggs/larvae
    """

    variables = Lagrangian3DArray.add_variables([
        ('diameter', {'dtype': np.float32,
                      'units': 'm',
                      'default': 0.0014}),  # for NEA Cod
        ('neutral_buoyancy_salinity', {'dtype': np.float32,
                                       'units': '[]',
                                       'default': 31.25}),  # for NEA Cod
        ('density', {'dtype': np.float32,
                     'units': 'kg/m^3',
                     'default': 1028.}),
        ('hatched', {'dtype': np.float32,
                     'units': '',
                     'default': 0.}),
        ('terminal_velocity', {'dtype': np.float32,
                       'units': 'm/s',
                       'default': 0.})])


class LobsterLarvae(OceanDrift):
    """Buoyant particle trajectory model based on the OpenDrift framework.

        Developed at MET Norway

        Generic module for particles that are subject to vertical turbulent
        mixing with the possibility for positive or negative buoyancy

        Particles could be e.g. oil droplets, plankton, or sediments

        Under construction.
    """

    ElementType = LobsterLarvaeObj
    # ElementType = BuoyantTracer 

    required_variables = {
        'x_sea_water_velocity': {'fallback': 0},
        'y_sea_water_velocity': {'fallback': 0},
        'sea_surface_wave_significant_height': {'fallback': 0},
        'sea_ice_area_fraction': {'fallback': 0},
        'x_wind': {'fallback': 0},
        'y_wind': {'fallback': 0},
        'land_binary_mask': {'fallback': None},
        'sea_floor_depth_below_sea_level': {'fallback': 100},
        'ocean_vertical_diffusivity': {'fallback': 0.02, 'profiles': True},
        'sea_water_temperature': {'fallback': 15, 'profiles': True},
        'sea_water_salinity': {'fallback': 34, 'profiles': True},
        'sea_surface_height': {'fallback': 0.0},
        'surface_downward_x_stress': {'fallback': 0},
        'surface_downward_y_stress': {'fallback': 0},
        'turbulent_kinetic_energy': {'fallback': 0},
        'turbulent_generic_length_scale': {'fallback': 0},
        'upward_sea_water_velocity': {'fallback': 0},
      }

    # Vertical profiles of the following parameters will be available in
    # dictionary self.environment.vertical_profiles
    # E.g. self.environment_profiles['x_sea_water_velocity']
    # will be an array of size [vertical_levels, num_elements]
    # The vertical levels are available as
    # self.environment_profiles['z'] or
    # self.environment_profiles['sigma'] (not yet implemented)

    # required_profiles = ['sea_water_temperature',
    #                      'sea_water_salinity',
    #                      'ocean_vertical_diffusivity']

    # removing salt/water temp profile requirement for now
    # > need to get correct profiles from SCHISM reader

    # required_profiles = ['ocean_vertical_diffusivity']

    # The depth range (in m) which profiles shall cover
    required_profiles_z_range = [-120, 0]

    # Default colors for plotting
    status_colors = {'initial': 'green', 'active': 'blue',
                     'settled_on_coast': 'red', 'died': 'yellow', 'settled_on_bottom': 'magenta'}

    def __init__(self, *args, **kwargs):
        
        # Calling general constructor of parent class
        super(LobsterLarvae, self).__init__(*args, **kwargs)

        # By default, larvae do not strand when reaching shoreline. 
        # They are recirculated back to previous position instead
        self.set_config('general:coastline_action', 'previous')

        # resuspend larvae that reach seabed by default 
        self.set_config('drift:lift_to_seafloor',True)
        # set the defasult min_settlement_age_seconds to 0.0
        # self.set_config('drift:min_settlement_age_seconds', '0.0')

        ##add config spec
        self._add_config({ 'drift:min_settlement_age_seconds': {'type': 'float', 'default': 0.0,'min': 0.0, 'max': 1.0e10, 'units': 'seconds',
                           'description': 'minimum age in seconds at which larvae can start to settle on seabed or stick to shoreline)',
                           'level': self.CONFIG_LEVEL_BASIC}})
        self._add_config({ 'drift:settlement_in_habitat': {'type': 'bool', 'default': False,
                           'description': 'settlement restricted to suitable habitat only',
                           'level': self.CONFIG_LEVEL_BASIC}})
        self._add_config({ 'drift:direct_orientation_habitat': {'type': 'bool', 'default': False,
                           'description': 'biased correlated random walk toward the nearest habitat',
                           'level': self.CONFIG_LEVEL_BASIC}})						   
        
        
    def habitat(self, shapefile_location):
        """Suitable habitat in a shapefile"""
        global multiShp
        global centers
        polyShp = fiona.open(shapefile_location) # import shapefile
        polyList = []
        #polyProperties = []
        centers = []
        for poly in polyShp: # create individual polygons from shapefile
             polyGeom = Polygon(poly['geometry']['coordinates'][0]) 
             polyList.append(polyGeom) # Compile polygon in a list
             centers.append(list(polyGeom.centroid.coords)) # Compute centroid and return a [lon, lat] list
             #polyProperties.append(poly['properties']) # For debugging => check if single polygon
        multiShp = MultiPolygon(polyList).buffer(0) # Aggregate polygons in a MultiPolygon object and buffer to fuse polygons and remove errors
        return multiShp, centers
		
    # Haversine formula to compute distances
    @numba.jit(nopython=True)
    def haversine_distance(s_lng,s_lat,e_lng,e_lat):
        # approximate radius of earth in km
        R = 6373.0
        s_lat = np.deg2rad(s_lat)                    
        s_lng = np.deg2rad(s_lng)     
        e_lat = np.deg2rad(e_lat)                       
        e_lng = np.deg2rad(e_lng)
        d = np.sin((e_lat - s_lat)/2)**2 + \
           np.cos(s_lat)*np.cos(e_lat) * \
           np.sin((e_lng - s_lng)/2)**2
        return 2 * R * np.arcsin(np.sqrt(d))
    
	# Haversine formula to compute angles
    @numba.jit(nopython=True)
    def haversine_angle(lon1, lat1, lon2, lat2):
        rlat1 = np.deg2rad(lat1)
        rlat2 = np.deg2rad(lat2)
        rlon1 = np.deg2rad(lon1)
        rlon2 = np.deg2rad(lon2)
        X = np.cos(rlat2)*np.sin(rlon2-rlon1)
        Y = np.cos(rlat1)*np.sin(rlat2)-np.sin(rlat1)*np.cos(rlat2)*np.cos(rlon2-rlon1)
        return np.arctan2(Y,X)

    def nearest_habitat(lon, lat, centers):
        dist = np.zeros(len(centers))
        dist = haversine_distance(lon, lat, centers[:, 0], centers[:, 1])
        nearest_center = np.argmin(dist)
        return nearest_center, min(dist)


    def update_terminal_velocity(self, Tprofiles=None,
                                 Sprofiles=None, z_index=None):
        pass
#       self.elements.terminal_velocity = W

    def sea_surface_height(self):
        '''fetches sea surface height for presently active elements
           sea_surface_height > 0 above mean sea level
           sea_surface_height < 0 below mean sea level
        '''
        if hasattr(self, 'environment') and \
                hasattr(self.environment, 'sea_surface_height'):
            if len(self.environment.sea_surface_height) == \
                    self.num_elements_active():
                sea_surface_height = \
                    self.environment.sea_surface_height
        if 'sea_surface_height' not in locals():
            env, env_profiles, missing = \
                self.get_environment(['sea_surface_height'],
                                     time=self.time, lon=self.elements.lon,
                                     lat=self.elements.lat,
                                     z=0*self.elements.lon, profiles=None)
            sea_surface_height = \
                env['sea_surface_height'].astype('float32') 
        return sea_surface_height   

    def update(self):
        """Update positions and properties of buoyant particles."""

        # Update element age
        # self.elements.age_seconds += self.time_step.total_seconds()
        # already taken care of in increase_age_and_retire() in basemodel.py

        # Horizontal advection
        # Check for presence in habitat
        if self.get_config('drift:direct_orientation') is True:
            self.advect_ocean_current()
            self.direct_orientation_habitat()
        else:
            self.advect_ocean_current()
        
        # Check for presence in habitat
        if self.get_config('drift:settlement_in_habitat') is True:
            self.interact_with_habitat()

        # Turbulent Mixing or settling-only 
        if self.get_config('drift:vertical_mixing') is True:
            self.update_terminal_velocity()  #compute vertical velocities, two cases possible - constant, or same as pelagic egg
            self.vertical_mixing()
        else:  # Buoyancy
            self.update_terminal_velocity()
            self.vertical_buoyancy()

        self.vertical_advection()     


    def interact_with_seafloor(self):
        """Seafloor interaction according to configuration setting"""
        # 
        # This function will overloads the version in basemodel.py
        if self.num_elements_active() == 0:
            return
        if 'sea_floor_depth_below_sea_level' not in self.priority_list:
            return
        sea_floor_depth = self.sea_floor_depth()
        below = np.where(self.elements.z < -sea_floor_depth)[0]
        if len(below) == 0:
                logger.debug('No elements hit seafloor.')
                return

        below_and_older = np.logical_and(self.elements.z < -sea_floor_depth, 
            self.elements.age_seconds >= self.get_config('drift:min_settlement_age_seconds'))
        below_and_younger = np.logical_and(self.elements.z < -sea_floor_depth, 
            self.elements.age_seconds < self.get_config('drift:min_settlement_age_seconds'))
        
        # Move all elements younger back to seafloor 
        # (could rather be moved back to previous if relevant? )
        self.elements.z[np.where(below_and_younger)] = -sea_floor_depth[np.where(below_and_younger)]

        # deactivate elements that were both below and older
        if self.get_config('drift:settlement_in_habitat') is False:
            self.deactivate_elements(below_and_older ,reason='settled_on_bottom')
        # if elements can only settle in habitat then they are moved back to seafloor
        else:
            self.elements.z[np.where(below_and_older)] = -sea_floor_depth[np.where(below_and_older)]

        logger.debug('%s elements hit seafloor, %s were older than %s sec. and deactivated, %s were lifted back to seafloor' \
            % (len(below),len(below_and_older),self.get_config('drift:min_settlement_age_seconds'),len(below_and_younger)))    


    def surface_stick(self):
        '''Keep particles just below the surface.
           (overloads the OpenDrift3DSimulation version to allow for possibly time-varying
           sea_surface_height)
        '''
        
        sea_surface_height = self.sea_surface_height() # returns surface elevation at particle positions (>0 above msl, <0 below msl)
        
        # keep particle just below sea_surface_height (self.elements.z depth are negative down)
        surface = np.where(self.elements.z >= sea_surface_height)
        if len(surface[0]) > 0:
            self.elements.z[surface] = sea_surface_height[surface] -0.01 # set particle z at 0.01m below sea_surface_height
            
    
    def interact_with_coastline(self,final = False): 
        """Coastline interaction according to configuration setting
           (overloads the interact_with_coastline() from basemodel.py)
           
           The method checks for age of particles that intersected coastlines:
             if age_particle < min_settlement_age_seconds : move larvaes back to previous wet position
             if age_particle > min_settlement_age_seconds : larvaes become stranded and will be deactivated.
        """
        i = self.get_config('general:coastline_action') # will always be 'previous'

        if not hasattr(self.environment, 'land_binary_mask'):
            return

        if final is True:  # Get land_binary_mask for final location
            en, en_prof, missing = \
                self.get_environment(['land_binary_mask'],
                                     self.time,
                                     self.elements.lon,
                                     self.elements.lat,
                                     self.elements.z,
                                     None)
            self.environment.land_binary_mask = en.land_binary_mask

        # if i == 'previous':  # Go back to previous position (in water)
        # previous_position_if = self.previous_position_if()
        if self.newly_seeded_IDs is not None:
                self.deactivate_elements(
                    (self.environment.land_binary_mask == 1) &
                    (self.elements.age_seconds == self.time_step.total_seconds()),
                    reason='seeded_on_land')
        on_land = np.where(self.environment.land_binary_mask == 1)[0]

            # if previous_position_if is not None:
            #     self.deactivate_elements((previous_position_if*1 == 1) & (
            #                      self.environment.land_binary_mask == 0),
            #                          reason='seeded_at_nodata_position')

        # if previous_position_if is None:
        #     on_land = np.where(self.environment.land_binary_mask == 1)[0]
        # else:
        #     on_land = np.where((self.environment.land_binary_mask == 1) |
        #                        (previous_position_if == 1))[0]
        if len(on_land) == 0:
            logger.debug('No elements hit coastline.')
        else:
            if self.get_config('drift:settlement_in_habitat') is True:
                    # Particle can only settle in habitat, set back to previous location
                    logger.debug('%s elements hit coastline, '
                              'moving back to water' % len(on_land))
                    on_land_ID = self.elements.ID[on_land]
                    self.elements.lon[on_land] = \
                        np.copy(self.previous_lon[on_land_ID - 1])
                    self.elements.lat[on_land] = \
                        np.copy(self.previous_lat[on_land_ID - 1])
                    self.environment.land_binary_mask[on_land] = 0  
            elif self.get_config('drift:min_settlement_age_seconds') == 0.0 :
                # No minimum age input, set back to previous position (same as in interact_with_coastline() from basemodel.py)
                logger.debug('%s elements hit coastline, '
                          'moving back to water' % len(on_land))
                on_land_ID = self.elements.ID[on_land]
                self.elements.lon[on_land] = \
                    np.copy(self.previous_lon[on_land_ID - 1])
                self.elements.lat[on_land] = \
                    np.copy(self.previous_lat[on_land_ID - 1])
                self.environment.land_binary_mask[on_land] = 0
            else:
                #################################
                # Minimum age before settling was input; check age of particle versus min_settlement_age_seconds
                # and strand or recirculate accordingly
                on_land_and_younger = np.where((self.environment.land_binary_mask == 1) & (self.elements.age_seconds < self.get_config('drift:min_settlement_age_seconds')))[0]
                #on_land_and_older = np.where((self.environment.land_binary_mask == 1) & (self.elements.age_seconds >= self.get_config('drift:min_settlement_age_seconds')))[0]

                # this step replicates what is done is original code, but accounting for particle age. It seems necessary 
                # to have an array of ID, rather than directly indexing using the "np.where-type" index (in dint64)
                on_land_and_younger_ID = self.elements.ID[on_land_and_younger] 
                #on_land_and_older_ID = self.elements.ID[on_land_and_older]

                logger.debug('%s elements hit coastline' % len(on_land))
                logger.debug('moving %s elements younger than min_settlement_age_seconds back to previous water position' % len(on_land_and_younger))
                logger.debug('%s elements older than min_settlement_age_seconds remain stranded on coast' % len(on_land_and_younger))
                
                # refloat elements younger than min_settlement_age back to previous position(s)
                if len(on_land_and_younger) > 0 :
                    # self.elements.lon[np.where(on_land_and_younger)] = np.copy(self.previous_lon[np.where(on_land_and_younger)])  
                    # self.elements.lat[np.where(on_land_and_younger)] = np.copy(self.previous_lat[np.where(on_land_and_younger)])
                    # self.environment.land_binary_mask[on_land_and_younger] = 0 

                    self.elements.lon[on_land_and_younger] = np.copy(self.previous_lon[on_land_and_younger_ID - 1])
                    self.elements.lat[on_land_and_younger] = np.copy(self.previous_lat[on_land_and_younger_ID - 1])
                    self.environment.land_binary_mask[on_land_and_younger] = 0

                # deactivate elements older than min_settlement_age & save position
                # ** function expects an array of size consistent with self.elements.lon
                self.deactivate_elements((self.environment.land_binary_mask == 1) & \
                                         (self.elements.age_seconds >= self.get_config('drift:min_settlement_age_seconds')),
                                         reason='settled_on_coast')

    
    def interact_with_habitat(self):
           """Habitat interaction according to configuration setting
               The method checks if a particle is within the limit of an habitat before to allow settlement
           """        
           # Get age of particle
           old_enough = np.where(self.elements.age_seconds >= self.get_config('drift:min_settlement_age_seconds'))[0]
           if len(old_enough) > 0 :
               pts_lon = self.elements.lon[old_enough]
               pts_lat = self.elements.lat[old_enough]
               # Check if position of particle is within boundaries of polygons
               for i in range(len(pts_lon)): # => faster version
                    pt = Point(pts_lon[i], pts_lat[i])
                    in_habitat = pt.within(multiShp)
                    if in_habitat == True:
                        self.environment.land_binary_mask[old_enough[i]] = 6
                           
           # Deactivate elements that are within a polygon and old enough to settle
           # ** function expects an array of size consistent with self.elements.lon                
           self.deactivate_elements((self.environment.land_binary_mask == 6), reason='home_sweet_home')
		
		
    def direct_orientation_habitat(self):
	        """Biased correlated random walk toward the nearest habitat - equations described in Codling et al., 2004"""
		     
			

        
    def increase_age_and_retire(self):  # ##So that if max_age_seconds is exceeded particle is flagged as died
            """Increase age of elements, and retire if older than config setting.

               >essentially same as increase_age_and_retire() from basemodel.py, 
               only using a diffrent reason for retiring particles ('died' instead of 'retired')
               .. could probably be removed...
            """
            # Increase age of elements
            self.elements.age_seconds += self.time_step.total_seconds()

            # Deactivate elements that exceed a certain age
            if self.get_config('drift:max_age_seconds') is not None:
                self.deactivate_elements(self.elements.age_seconds >=
                                         self.get_config('drift:max_age_seconds'),
                                         reason='died')

            # Deacticate any elements outside validity domain set by user
            if self.validity_domain is not None:
                W, E, S, N = self.validity_domain
                if W is not None:
                    self.deactivate_elements(self.elements.lon < W, reason='outside')
                if E is not None:
                    self.deactivate_elements(self.elements.lon > E, reason='outside')
                if S is not None:
                    self.deactivate_elements(self.elements.lat < S, reason='outside')
                if N is not None:
                    self.deactivate_elements(self.elements.lat > N, reason='outside')