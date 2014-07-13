from functools import partial
import config as cfg
import numpy as np
from minimization import minimize_with_restarts
from sklearn.cross_validation import LeaveOneOut, KFold
from shapes.priors import get_prior
from numpy import linalg

class Fitter(object):
    def __init__(self, shape, sigma_prior=None):
        self.shape = shape
        if shape.has_special_fitting() and sigma_prior is not None:
            raise Exception("Sigma prior can't be used with a shape that has special fitting")
        self.inv_sigma_prior_name = sigma_prior
        self.inv_sigma_prior = get_prior(sigma_prior,is_sigma=True)
        if cfg.verbosity > 0:
            if self.shape.priors is not None:
                print 'Fitting using prior {} on theta:'.format(self.shape.priors_name)
                for name,pr in zip(self.shape.param_names(), self.shape.priors):
                    print '\t{}: {}'.format(name,pr)
            if self.inv_sigma_prior is not None:
                print 'Fitting using prior on 1/sigma = {}'.format(self.inv_sigma_prior)
        
    def __str__(self):
        return 'Fitter({}, theta_prior={}, inv_sigma_prior={})'.format(self.shape, self.shape.priors_name, self.inv_sigma_prior_name)
        
    def cache_name(self):
        name = self.shape.cache_name()
        if self.shape.priors is not None:
            name = '{}-theta-{}'.format(name,self.shape.priors_name)
        if self.inv_sigma_prior is not None:
            name = '{}-sigma-{}'.format(name,self.inv_sigma_prior_name)
        return name
        
    def format_params(self, theta, sigma, latex=False):
        shape_params = self.shape.format_params(theta,latex)
        if latex:
            return r'{}, $\sigma$={:.2f}'.format(shape_params, sigma)
        else:
            return r'{}, sigma={:.2f}'.format(shape_params, sigma)

    def fit(self, x, y, loo=False):
        assert x.ndim == 1
        assert y.ndim <= 2
        assert y.shape[0] == len(x)
        n_series = y.shape[1] if y.ndim == 2 else 1
        
        t0,s0 = self._fit(x,y)
        if loo:            
            n = y.size
            test_preds = np.empty(y.shape)
            test_fits = np.empty(y.shape, dtype=object)
            
            k = cfg.n_folds
            if k == 0 or k>=n:
                train_test_split = LeaveOneOut(n)
                n_batches = n
            else:
                rng = np.random.RandomState(cfg.random_seed)
                train_test_split = KFold(n,k,shuffle=True, random_state=rng)
                n_batches = k
                
            for i,(train,test) in enumerate(train_test_split):
                if cfg.verbosity >= 2:
                    print 'LOO fit: computing prediction for points {} (batch {}/{})'.format(list(test),i,n_batches)
                if n_series == 1:
                    theta,sigma = self._fit(x[train],y[train])
                    for idxTest in test:
                        test_fits[idxTest] = (theta,sigma) # assigning tuple to list of indices does something different (not sure what...)
                    if theta is None:
                        test_preds[test] = np.nan
                    else:
                        test_preds[test] = self.shape.f(theta,x[test])
                else:
                    y_train = np.copy(y)
                    y_train.ravel()[test] = np.NaN # remove information for test-set points
                    theta,sigma = self._fit(x,y_train)
                    for idxTest in test:
                        test_fits[idxTest] = (theta,sigma) # assigning tuple to list of indices does something different (not sure what...)
                    if theta is None:
                        test_preds.ravel()[test] = np.NaN
                    else:
                        L = linalg.inv(sigma)
                        for idx_test in test:
                            idx_x = int(idx_test / n_series)
                            idx_y = idx_test % n_series
                            y_other = np.copy(y[idx_x,:])
                            y_other[idx_y] = np.NaN
                            test_preds.ravel()[idx_test] = self._predict_with_covariance(theta, L, x[idx_x], y_other, idx_y)
        else:
            test_preds = None
            test_fits = None
        return t0, s0, test_preds, test_fits
        
    def _predict_with_covariance(self, theta, L, x, y_other, k):
        """Predicts value for series number k at value x (both scalars).
           Theta contains a set of fit parameters for each series.
           L is the precision matrix (inverse of the covariance matrix) showing the covariance
           between different series for each subject.
           The prediction is based on the mean value across subjects at x f(theta,x) and
           the per-subject variation for series k is estimated from the variations of the other series
           using the precision matrix L.
           The predicted value of the "noise", dy, is the mean of the conditional 
           Gaussian distribution, given the other y values. See Bishop p. 87, eq. 2.75.
        """        
        assert np.isnan(y_other[k])
        y0 = self.shape.f(theta[k],x)
        dy_other = np.array([yi - self.shape.f(t,x) for t,yi in zip(theta,y_other)]) # dy_other[k] will be NaN
        dy_other[np.isnan(dy_other)] = 0 # ignore in dot product (includes index k)
        dy = -np.dot(dy_other,L[k,:]) / L[k,k]
        return y0 + dy

    def translate_parameters_to_priors_scale(self,x,y,theta,sigma):
        """Priors for the parameters are specified for data that is already 
           scaled linearly to [-1,1].
           The parameters are then adjusted to the original scale of the data.
           In order to examine the distribution of the parameters, e.g. for applying
           empirical Bayes, we need to translate the parameters back their values
           when applied to the scaled data.
           This method finds the scaling that was used during fitting and applies
           the reverse adjustment to the parameters to recover their original
           values before adjustment.
        """
        x,sx = self._scale(x)
        y,sy = self._scale(y)
        isx = self._inverse_scaling(sx)
        isy = self._inverse_scaling(sy)
        sigma = sigma / isy[0]
        theta = self.shape.adjust_for_scaling(theta,isx,isy)
        return theta,sigma

    ##########################################################
    # Private methods for fitting
    ##########################################################

    def _fit(self,x,y):
        if self.shape.has_special_fitting():
            assert y.ndim == 1, "Fitting for {} with multiple series not supported yet".format(self.shape)
            theta = self.shape.fit(x,y)
            y_fit = self.shape.f(theta,x)
            sigma = np.std(y - y_fit)
            return theta,sigma
        else:
            return self._gradient_fit(x,y)
            
    def _gradient_fit(self,x,y):
        if y.ndim == 1:
            return self._gradient_fit_single_series(x,y)
        n_series = y.shape[1]
        theta_sigma_pairs = [self._gradient_fit_single_series(x,y[:,i]) for i in xrange(n_series)]
        theta = [t for t,s in theta_sigma_pairs]
        sigma = self._calc_covariance_matrix(theta,x,y)
        return theta,sigma
        
    def _calc_covariance_matrix(self,theta,x,y):
        """Maximum likelihood for the covariance matrix is just the empirical covariance
           matrix. See Bishop p. 93-94
        """
        f_vals = np.empty(y.shape)
        for i,ti in enumerate(theta):
            f_vals[:,i] = self.shape.f(ti,x)
        r = y - f_vals
        r = np.ma.masked_array(r, np.isnan(r))
        C = np.ma.cov(r,rowvar=0)
        return C
        
    def _gradient_fit_single_series(self,x,y):
        assert y.ndim == 1
        valid = ~np.isnan(y)
        y = y[valid]
        x = x[valid]
        x,sx = self._scale(x)
        y,sy = self._scale(y)
        n_restarts = cfg.n_optimization_restarts
        rng = np.random.RandomState(cfg.random_seed)
        np.random.seed(cfg.random_seed) # for prior.generate() which doesn't have a way to control rng
        P0_base = np.array(self.shape.get_theta_guess(x,y) + [1])
        def get_P0(i):
            # if we're using priors, draw from the prior distribution
            P0 = P0_base + rng.normal(0,0.1,size=P0_base.shape)
            if self.shape.priors is not None:
                P0[:-1] = np.array([pr.generate() for pr in self.shape.priors])
            if self.inv_sigma_prior is not None:
                P0[-1] = self.inv_sigma_prior.generate()
            return P0
        f = partial(self._Err, x=x, y=y)
        f_grad = partial(self._Err_grad, x=x, y=y)
        theta_bounds = self.shape.bounds()
        if self.inv_sigma_prior is not None:
            p_bounds = self.inv_sigma_prior.bounds()
        else:
            p_bounds = (None,None)
        bounds = theta_bounds + [p_bounds]
        P = minimize_with_restarts(f, f_grad, get_P0, bounds, n_restarts)
        if P is None:
            return None,None
        theta = P[:-1]
        sigma = 1/P[-1]

        # adjust theta and sigma to compensate for the scaling
        sigma = sigma / sy[0]
        theta = self.shape.adjust_for_scaling(theta,sx,sy)
        return theta,sigma

    @staticmethod
    def _scale(vals):
        vLow,vHigh = np.percentile(vals, cfg.fitter_scaling_percentiles)
        vRange = vHigh - vLow
        vCenter = 0.5 * (vHigh + vLow)
        b = vCenter
        a = 2.0/vRange
        scaledVals = a*(vals-b) # translate the range [vLow,vHigh] to [-1,1]
        return scaledVals,(a,b)

    @staticmethod
    def _inverse_scaling(s):
        a,b = s
        ia = 1/a
        ib = -a*b
        return ia,ib
      
    def _Err(self,P,x,y):
        theta,p = P[:-1],P[-1]
        diffs = self.shape.f(theta,x) - y
        residuals_term = 0.5 * p**2 * sum(diffs**2)
        n = len(y)
        E = -n*np.log(p) + residuals_term
        if self.shape.priors is not None:
            E = E - self.shape.log_prob_theta(theta)
        if self.inv_sigma_prior is not None:
            E = E - self.inv_sigma_prior.log_prob(p)
        return E
        
    def _Err_grad(self,P,x,y):
        theta,p = P[:-1],P[-1]
        n = len(y)
        diffs = self.shape.f(theta,x) - y
        d_theta = np.array([p**2 * sum(diffs*d) for d in self.shape.f_grad(theta,x)])
        if self.shape.priors is not None:
            d_theta = d_theta - self.shape.d_log_prob_theta(theta)
        d_p = -n/p + p*sum(diffs**2)
        if self.inv_sigma_prior is not None:
            d_p = d_p - self.inv_sigma_prior.d_log_prob(p)
        return np.r_[d_theta, d_p]
